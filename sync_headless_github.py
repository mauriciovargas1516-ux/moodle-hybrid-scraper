# -*- coding: utf-8 -*-
"""
sync_headless_github.py
Robot automático (GitHub Actions) para sincronizar apuntes de ULagos Virtual (Moodle)
y repartir archivos nuevos/actualizados hacia los repositorios de cada ramo vía GitHub API.
"""

import base64
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib3
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse, parse_qs, quote

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URL_LOGIN = "https://www.ulagosvirtual.cl/login/index.php"
MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB límite seguro para GitHub Contents API

# Extensiones de video prohibidas para mantener los repositorios livianos
EXTENSIONES_PROHIBIDAS = (".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm", ".m4v")

# Mapeo palabra clave del curso en Moodle -> Repositorio destino en GitHub
MAPEO_REPOS_CURSOS = {
    "tributaria": "GESTION-TRIBUTARIA-2026",
    "territorial": "DESARROLLO-Y-GESTION-TERRITORIAL-2026",
    "finanzas": "FINANZAS-AVANZADAS-2026",
    "proyectos": "PROYECTOS-2026",
}


def limpiar_nombre(nombre: str) -> str:
    limpio = re.sub(r'[\\/*?:"<>|]', "", str(nombre)).strip()
    limpio = re.sub(r"\s+", " ", limpio)
    return limpio[:120] if limpio else "documento"


def detectar_repo_destino(nombre_curso: str):
    low = nombre_curso.lower()
    for clave, repo in MAPEO_REPOS_CURSOS.items():
        if clave in low:
            return repo
    return None


def git_blob_sha(contenido: bytes) -> str:
    """Calcula el SHA-1 exacto de un blob de Git para evitar commits duplicados."""
    header = f"blob {len(contenido)}\0".encode("utf-8")
    return hashlib.sha1(header + contenido).hexdigest()


def configurar_driver_headless():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1366,768")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--lang=es-CL")
    options.add_argument("--accept-lang=es-CL,es;q=0.9")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    options.set_capability("acceptInsecureCerts", True)
    options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])

    ruta_chrome = (
        shutil.which("google-chrome")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    ruta_driver = shutil.which("chromedriver")

    if ruta_chrome:
        options.binary_location = ruta_chrome
    if ruta_chrome and ruta_driver:
        return webdriver.Chrome(service=Service(executable_path=ruta_driver), options=options)
    return webdriver.Chrome(options=options)


def iniciar_sesion_moodle(usuario: str, dominio: str, clave: str):
    driver = configurar_driver_headless()
    paso = "Abriendo portal ULagos Virtual"
    try:
        driver.set_page_load_timeout(40)
        driver.get(URL_LOGIN)

        paso = "Buscando campo de usuario"
        xpath_usuario = (
            "//input[@placeholder='Usuario' or @placeholder='Username' "
            "or @name='username' or @id='username' or @type='text']"
        )
        caja_usuario = WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.XPATH, xpath_usuario))
        )
        caja_usuario.clear()
        caja_usuario.send_keys(usuario.strip())

        paso = "Seleccionando dominio"
        selects = driver.find_elements(By.XPATH, "//select")
        if selects:
            menu = Select(selects[0])
            try:
                menu.select_by_visible_text(dominio)
            except Exception:
                for opt in menu.options:
                    if dominio in opt.text or dominio in (opt.get_attribute("value") or ""):
                        opt.click()
                        break

        paso = "Ingresando contraseña"
        xpath_clave = "//input[@placeholder='Contraseña' or @placeholder='Password' or @type='password']"
        caja_clave = driver.find_element(By.XPATH, xpath_clave)
        caja_clave.clear()
        caja_clave.send_keys(clave)

        paso = "Enviando formulario de login"
        xpath_boton = (
            "//button[contains(text(), 'Iniciar') or contains(text(), 'Acceder') "
            "or contains(text(), 'Log in') or @type='submit'] | //input[@type='submit']"
        )
        boton = driver.find_element(By.XPATH, xpath_boton)
        driver.execute_script("arguments[0].click();", boton)

        paso = "Esperando ingreso al Área Personal"
        WebDriverWait(driver, 35).until(lambda d: "login" not in d.current_url.lower())
        time.sleep(2.5)

        html_dash = driver.page_source
        cookies = driver.get_cookies()
    except Exception as e:
        url_err = ""
        try:
            url_err = driver.current_url
        except Exception:
            pass
        driver.quit()
        raise RuntimeError(f"Error en '{paso}' (URL: {url_err}): {type(e).__name__}: {e}") from e

    driver.quit()

    sesion = requests.Session()
    for c in cookies:
        sesion.cookies.set(c["name"], c["value"])
    sesion.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    })
    return sesion, html_dash


def extraer_pestanas_curso(url_curso: str, soup: BeautifulSoup) -> list:
    qs_base = parse_qs(urlparse(url_curso).query)
    curso_id = qs_base.get("id", [None])[0]
    urls_sec = set()

    for a in soup.find_all("a", href=True):
        href_abs = urljoin(url_curso, a["href"])
        if "course/section.php" in href_abs:
            urls_sec.add(href_abs)
        elif curso_id and "course/view.php" in href_abs and "section=" in href_abs:
            qs_link = parse_qs(urlparse(href_abs).query)
            if qs_link.get("id", [None])[0] == curso_id:
                urls_sec.add(href_abs)

    return sorted(urls_sec)


def descargar_recurso_memoria(sesion: requests.Session, url: str, num: int, nombre_sugerido=None):
    """Descarga un recurso de Moodle a memoria y devuelve (estado, nombre_archivo, bytes)."""
    ruta_url = urlparse(url).path.lower()
    if ruta_url.endswith(EXTENSIONES_PROHIBIDAS):
        print(f"  [IGNORADO - VIDEO] {os.path.basename(ruta_url)}")
        return "ignorados", None, None

    url_directa = url + "&redirect=1" if "view.php" in url and "redirect=1" not in url else url
    try:
        res = sesion.get(url_directa, verify=False, stream=True, timeout=25)
    except Exception:
        return "ignorados", None, None

    if res.status_code != 200:
        res.close()
        return "ignorados", None, None

    content_type = res.headers.get("Content-Type", "").lower()

    if "video/" in content_type:
        res.close()
        print(f"  [IGNORADO - VIDEO] {nombre_sugerido or url} ({content_type})")
        return "ignorados", None, None

    if "text/html" in content_type:
        soup_html = BeautifulSoup(res.text, "html.parser")
        titulo = (
            soup_html.find("h2").text
            if soup_html.find("h2")
            else (soup_html.title.text.replace("Curso:", "").strip() if soup_html.title else "Documento_Moodle")
        )
        titulo_limpio = limpiar_nombre(titulo)
        enlace_archivo = None

        objeto_pdf = soup_html.find("object", type="application/pdf")
        if objeto_pdf and "data" in objeto_pdf.attrs:
            enlace_archivo = objeto_pdf["data"]
        else:
            for a in soup_html.find_all("a", href=True):
                href = a["href"].lower()
                if urlparse(href).path.endswith(EXTENSIONES_PROHIBIDAS):
                    continue
                if "pluginfile.php" in href or any(
                    href.endswith(ext) for ext in [".pdf", ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".zip"]
                ):
                    enlace_archivo = a["href"]
                    break

        if enlace_archivo:
            return descargar_recurso_memoria(sesion, urljoin(url, enlace_archivo), num, titulo_limpio)
        return "ignorados", None, None

    nombre_base = nombre_sugerido if nombre_sugerido else f"apunte_{num}"
    ext_final = ""

    if "Content-Disposition" in res.headers:
        cd = res.headers["Content-Disposition"]
        if "filename=" in cd:
            nombre_real = cd.split("filename=")[1].split(";")[0].strip("\"' ").replace('"', "")
            _, ext = os.path.splitext(nombre_real)
            if ext:
                ext_final = ext.lower()
                if not nombre_sugerido:
                    nombre_base = nombre_real[:-len(ext)]

    if not ext_final:
        if "spreadsheet" in content_type or "excel" in content_type:
            ext_final = ".xlsx"
        elif "word" in content_type:
            ext_final = ".docx"
        elif "presentation" in content_type or "powerpoint" in content_type:
            ext_final = ".pptx"
        elif "zip" in content_type:
            ext_final = ".zip"
        else:
            ext_final = ".pdf"

    # Filtro anti-videos en streaming antes de bajar el cuerpo a RAM
    if ext_final in EXTENSIONES_PROHIBIDAS or (
        nombre_sugerido and nombre_sugerido.lower().endswith(EXTENSIONES_PROHIBIDAS)
    ):
        res.close()
        print(f"  [IGNORADO - VIDEO] {limpiar_nombre(nombre_base)}{ext_final}")
        return "ignorados", None, None

    # Filtro previo por cabecera Content-Length para no descargar archivos gigantes
    content_length = res.headers.get("Content-Length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_FILE_BYTES:
        res.close()
        mb = int(content_length) / (1024 * 1024)
        print(f"  [IGNORADO - PESADO] {limpiar_nombre(nombre_base)}{ext_final} ({mb:.1f} MB)")
        return "ignorados", None, None

    contenido = res.content
    if len(contenido) == 0 or len(contenido) > MAX_FILE_BYTES:
        return "ignorados", None, None

    nombre_archivo = limpiar_nombre(nombre_base) + ext_final
    if nombre_archivo.lower().endswith(EXTENSIONES_PROHIBIDAS):
        print(f"  [IGNORADO - VIDEO] {nombre_archivo}")
        return "ignorados", None, None

    return "ok", nombre_archivo, contenido


class ClienteGitHubSync:
    def __init__(self, token: str, owner: str):
        self.owner = owner
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        self.cache_dirs = {}

    def listar_carpeta(self, repo: str, carpeta: str) -> dict:
        clave = f"{repo}/{carpeta}"
        if clave in self.cache_dirs:
            return self.cache_dirs[clave]

        url = f"https://api.github.com/repos/{self.owner}/{repo}/contents/{quote(carpeta)}"
        r = self.session.get(url, timeout=20)
        mapa = {}
        if r.status_code == 200 and isinstance(r.json(), list):
            for item in r.json():
                if item.get("type") == "file":
                    mapa[item["name"]] = item["sha"]
        self.cache_dirs[clave] = mapa
        return mapa

    def subir_si_cambio(self, repo: str, carpeta: str, nombre_archivo: str, contenido: bytes) -> str:
        """
        Retorna: 'nuevo' | 'actualizado' | 'sin_cambios' | 'error'
        """
        existentes = self.listar_carpeta(repo, carpeta)
        sha_local = git_blob_sha(contenido)
        sha_remoto = existentes.get(nombre_archivo)

        if sha_remoto == sha_local:
            return "sin_cambios"

        ruta = f"{carpeta}/{nombre_archivo}"
        url = f"https://api.github.com/repos/{self.owner}/{repo}/contents/{quote(ruta)}"
        payload = {
            "message": f"Robot Moodle: {'actualizar' if sha_remoto else 'agregar'} {nombre_archivo}",
            "content": base64.b64encode(contenido).decode("ascii"),
        }
        if sha_remoto:
            payload["sha"] = sha_remoto

        r = self.session.put(url, json=payload, timeout=35)
        if r.status_code in (200, 201):
            nuevo_sha = r.json().get("content", {}).get("sha", sha_local)
            existentes[nombre_archivo] = nuevo_sha
            return "actualizado" if sha_remoto else "nuevo"

        print(f"  [ERROR GitHub {r.status_code}] {repo}/{ruta}: {r.text[:180]}")
        return "error"


def main():
    usuario = os.environ.get("MOODLE_USER", "").strip()
    clave = os.environ.get("MOODLE_PASS", "").strip()
    dominio = os.environ.get("MOODLE_DOMAIN", "@alumnos.ulagos.cl").strip() or "@alumnos.ulagos.cl"
    gh_pat = os.environ.get("GH_PAT_SYNC", "").strip()
    gh_owner = os.environ.get("GH_OWNER", "mauriciovargas1516-ux").strip()
    carpeta_dest = os.environ.get("CARPETA_DESTINO_REPO", "apuntes_moodle").strip() or "apuntes_moodle"

    ahora_utc = datetime.now(timezone.utc)
    ahora_cl = ahora_utc - timedelta(hours=3)

    reporte = {
        "fecha_utc": ahora_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "fecha_chile": ahora_cl.strftime("%Y-%m-%d %H:%M Chile"),
        "estado": "EN_PROCESO",
        "carpeta_destino": carpeta_dest,
        "push_multirepo_activo": bool(gh_pat),
        "resumen": {
            "cursos_revisados": 0,
            "nuevos_subidos": 0,
            "actualizados": 0,
            "sin_cambios": 0,
            "ignorados": 0,
            "errores": 0,
        },
        "repos": {},
        "novedades": [],
        "nota": "",
    }

    if not usuario or not clave:
        reporte["estado"] = "ERROR_CONFIG"
        reporte["nota"] = "Faltan secrets MOODLE_USER o MOODLE_PASS en GitHub Actions."
        with open("ultimo_sync.json", "w", encoding="utf-8") as f:
            json.dump(reporte, f, ensure_ascii=False, indent=2)
        print(reporte["nota"])
        sys.exit(1)

    print(f"[{reporte['fecha_chile']}] Iniciando Robot Moodle ULagos Virtual...")
    try:
        sesion, html_dash = iniciar_sesion_moodle(usuario, dominio, clave)
    except Exception as e:
        reporte["estado"] = "ERROR_LOGIN"
        reporte["nota"] = str(e)
        with open("ultimo_sync.json", "w", encoding="utf-8") as f:
            json.dump(reporte, f, ensure_ascii=False, indent=2)
        print(f"Fallo de login: {e}")
        sys.exit(1)

    soup_dash = BeautifulSoup(html_dash, "html.parser")
    cursos = {}
    for a in soup_dash.find_all("a", href=True):
        if "course/view.php?id=" in a["href"] and "section=" not in a["href"]:
            nombre = re.sub(r"\s+", " ", a.text.replace("Haga clic aquí para entrar al curso", "")).strip()
            if len(nombre) > 5 and nombre not in cursos.values():
                cursos[a["href"]] = nombre

    if not cursos:
        cursos["https://www.ulagosvirtual.cl/course/view.php?id=4056"] = "Gestión Tributaria para la Toma de Decisiones"

    gh_client = ClienteGitHubSync(gh_pat, gh_owner) if gh_pat else None
    if not gh_client:
        reporte["nota"] = "Ejecutado en modo lectura (falta secret GH_PAT_SYNC para subir a los repositorios de cada ramo)."
        print("AVISO:", reporte["nota"])

    for url_curso, nombre_curso in cursos.items():
        repo_dest = detectar_repo_destino(nombre_curso)
        reporte["resumen"]["cursos_revisados"] += 1
        print(f"\n>>> Curso: {nombre_curso} -> Repo destino: {repo_dest or '(sin mapeo)'}")

        try:
            html_curso = sesion.get(url_curso, verify=False, timeout=25).text
        except Exception as e:
            print(f"  [ERROR] No se pudo abrir el curso: {e}")
            reporte["resumen"]["errores"] += 1
            continue

        soup = BeautifulSoup(html_curso, "html.parser")
        enlaces_raw = soup.find_all("a", href=True)

        links_recurso = set(
            urljoin(url_curso, a["href"]) for a in enlaces_raw
            if any(k in a["href"] for k in ("resource/view.php", "pluginfile.php", "url/view.php"))
        )
        links_carpetas = set(
            urljoin(url_curso, a["href"]) for a in enlaces_raw if "folder/view.php" in a["href"]
        )
        links_pestanas = extraer_pestanas_curso(url_curso, soup)

        for carp_url in links_carpetas:
            try:
                r_c = sesion.get(carp_url, verify=False, timeout=20)
                for a in BeautifulSoup(r_c.text, "html.parser").find_all("a", href=True):
                    if "pluginfile.php" in a["href"] and "forcedownload=1" in a["href"]:
                        l_full = urljoin(carp_url, a["href"])
                        links_recurso.add(l_full.split("?")[0])
            except Exception:
                pass

        for sec_url in links_pestanas:
            try:
                r_s = sesion.get(sec_url, verify=False, timeout=20)
                for a in BeautifulSoup(r_s.text, "html.parser").find_all("a", href=True):
                    if any(k in a["href"] for k in ("resource/view.php", "pluginfile.php", "url/view.php")):
                        links_recurso.add(urljoin(sec_url, a["href"]))
            except Exception:
                pass

        info_repo = reporte["repos"].setdefault(
            repo_dest or nombre_curso,
            {"curso": nombre_curso, "total_detectados": 0, "nuevos": 0, "actualizados": 0, "sin_cambios": 0, "archivos": []},
        )

        vistos_en_curso = set()
        for idx_l, link in enumerate(sorted(links_recurso), start=1):
            est, nom, data = descargar_recurso_memoria(sesion, link, idx_l)
            if est != "ok" or not nom or data is None:
                reporte["resumen"]["ignorados"] += 1
                continue
            if nom in vistos_en_curso:
                continue
            vistos_en_curso.add(nom)
            info_repo["total_detectados"] += 1
            info_repo["archivos"].append(nom)

            if gh_client and repo_dest:
                res_up = gh_client.subir_si_cambio(repo_dest, carpeta_dest, nom, data)
                if res_up == "nuevo":
                    reporte["resumen"]["nuevos_subidos"] += 1
                    info_repo["nuevos"] += 1
                    reporte["novedades"].append(f"[NUEVO] {repo_dest}/{carpeta_dest}/{nom}")
                    print(f"  [NUEVO] {repo_dest}/{carpeta_dest}/{nom}")
                elif res_up == "actualizado":
                    reporte["resumen"]["actualizados"] += 1
                    info_repo["actualizados"] += 1
                    reporte["novedades"].append(f"[ACTUALIZADO] {repo_dest}/{carpeta_dest}/{nom}")
                    print(f"  [ACTUALIZADO] {repo_dest}/{carpeta_dest}/{nom}")
                elif res_up == "sin_cambios":
                    reporte["resumen"]["sin_cambios"] += 1
                    info_repo["sin_cambios"] += 1
                else:
                    reporte["resumen"]["errores"] += 1

    reporte["estado"] = "OK"
    with open("ultimo_sync.json", "w", encoding="utf-8") as f:
        json.dump(reporte, f, ensure_ascii=False, indent=2)

    print("\n=== RESUMEN ROBOT MOODLE ===")
    print(json.dumps(reporte["resumen"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
