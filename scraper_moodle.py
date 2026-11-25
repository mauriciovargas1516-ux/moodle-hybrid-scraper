# -*- coding: utf-8 -*-
import io
import os
import re
import time
import shutil
import json
import zipfile
import urllib3
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs

import requests
import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URL_LOGIN = "https://www.ulagosvirtual.cl/login/index.php"

st.set_page_config(
    page_title="Sincronizador ULagos Virtual",
    layout="wide",
)

st.title("Sincronizador Automatizado de Cursos Moodle")
st.markdown(
    "Extrae y empaqueta tus apuntes desde **ULagos Virtual** en un `.zip` organizado por ramo, "
    "con **Cámara en Vivo** para ver al navegador entrar al portal y rescatar los archivos en tiempo real."
)

# --- PANEL DE ESTADO DEL ROBOT AUTOMÁTICO (GITHUB ACTIONS) ---
if os.path.exists("ultimo_sync.json"):
    try:
        with open("ultimo_sync.json", "r", encoding="utf-8") as _fj:
            _rep = json.load(_fj)
        with st.expander(
            f"Robot Automático GitHub Actions — Última corrida: {_rep.get('fecha_chile', 'N/D')} ({_rep.get('estado', 'N/D')})",
            expanded=True,
        ):
            _res = _rep.get("resumen", {})
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Cursos revisados", _res.get("cursos_revisados", 0))
            c2.metric("Nuevos subidos", _res.get("nuevos_subidos", 0))
            c3.metric("Sin cambios", _res.get("sin_cambios", 0))
            c4.metric("Multi-repo activo", "Sí" if _rep.get("push_multirepo_activo") else "Pendiente PAT")
            if _rep.get("nota"):
                st.info(_rep["nota"])
            if _rep.get("novedades"):
                st.markdown("**Últimos archivos enviados a tus repositorios:**")
                for _nov in _rep["novedades"][:12]:
                    st.code(_nov, language=None)
            _repos_dict = _rep.get("repos", {})
            if _repos_dict:
                _filas_r = [
                    {
                        "Repositorio / Curso": k,
                        "Archivos detectados": v.get("total_detectados", 0),
                        "Nuevos": v.get("nuevos", 0),
                        "Sin cambios": v.get("sin_cambios", 0),
                    }
                    for k, v in _repos_dict.items()
                ]
                st.dataframe(pd.DataFrame(_filas_r), use_container_width=True, hide_index=True)
    except Exception:
        pass


# Leer credenciales desde st.secrets (seguro para repositorios públicos)
def _leer_secreto(clave: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(clave, default))
    except Exception:
        return default


user_default = _leer_secreto("MOODLE_USER", "")
pass_default = _leer_secreto("MOODLE_PASS", "")

with st.form("form_login_moodle"):
    st.subheader("Credenciales y Modo de Ejecución")
    col1, col2 = st.columns(2)

    with col1:
        usuario_input = st.text_input(
            "Usuario de ULagos",
            value=user_default,
            placeholder="ej. nombre.apellido",
            help="Primera parte de tu correo institucional, antes del @. Puedes guardarlo en Streamlit Secrets como MOODLE_USER.",
        )
        dominio_input = st.selectbox(
            "Dominio Institucional",
            options=["@alumnos.ulagos.cl", "@ulagos.cl"],
            index=0,
        )

    with col2:
        clave_input = st.text_input(
            "Contraseña",
            value=pass_default,
            type="password",
            help="Puedes guardarla en Streamlit Secrets como MOODLE_PASS para no escribirla cada vez.",
        )
        modo_camara = st.checkbox(
            "Activar Cámara en Vivo (ver ULagos Virtual abriéndose paso a paso)",
            value=True,
        )
        _es_windows = (os.name == "nt")
        modo_ventana_local = st.checkbox(
            "Abrir ventana real de Chrome (solo disponible en tu PC Windows)",
            value=False,
            disabled=not _es_windows,
        )

    iniciar_btn = st.form_submit_button("Lanzar Sincronización en Vivo", use_container_width=True)


# --- 1. CONFIGURACIÓN DEL NAVEGADOR ---
def configurar_driver(ventana_real: bool = False):
    options = Options()
    if not ventana_real:
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
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    options.set_capability("acceptInsecureCerts", True)
    options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])

    ruta_chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    ruta_chromedriver = shutil.which("chromedriver")

    if ruta_chromium and ruta_chromedriver:
        options.binary_location = ruta_chromium
        service = Service(executable_path=ruta_chromedriver)
        return webdriver.Chrome(service=service, options=options)

    return webdriver.Chrome(options=options)


def _capturar_frame(driver, camara_slot, leyenda: str, activo: bool = True, pausa: float = 0.4):
    if not activo or driver is None or camara_slot is None:
        return
    try:
        png = driver.get_screenshot_as_png()
        camara_slot.image(png, caption=leyenda, use_container_width=True)
        if pausa > 0:
            time.sleep(pausa)
    except Exception:
        pass


def abrir_sesion_con_camara(usuario, dominio, clave, camara_slot, log_fn, modo_camara=True, ventana_real=False):
    driver = configurar_driver(ventana_real=ventana_real)
    paso_actual = "Abriendo portal ULagos Virtual"
    try:
        driver.set_page_load_timeout(35)
        log_fn("Abriendo https://www.ulagosvirtual.cl/login/index.php ...")
        driver.get(URL_LOGIN)
        time.sleep(1.0)
        _capturar_frame(driver, camara_slot, "Paso 1: Portal de acceso ULagos Virtual abierto", modo_camara, 0.5)

        paso_actual = "Ingresando usuario y dominio"
        xpath_usuario = (
            "//input[@placeholder='Usuario' or @placeholder='Username' "
            "or @name='username' or @id='username' or @type='text']"
        )
        caja_usuario = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, xpath_usuario))
        )
        caja_usuario.clear()
        caja_usuario.send_keys(usuario.strip())

        selects = driver.find_elements(By.XPATH, "//select")
        if selects:
            menu_desplegable = Select(selects[0])
            try:
                menu_desplegable.select_by_visible_text(dominio)
            except Exception:
                for opt in menu_desplegable.options:
                    if dominio in opt.text or dominio in (opt.get_attribute("value") or ""):
                        opt.click()
                        break

        paso_actual = "Ingresando contraseña"
        xpath_clave = "//input[@placeholder='Contraseña' or @placeholder='Password' or @type='password']"
        caja_clave = driver.find_element(By.XPATH, xpath_clave)
        caja_clave.clear()
        caja_clave.send_keys(clave)
        log_fn(f"Credenciales ingresadas ({usuario.strip()}{dominio}). Pulsando Iniciar sesión...")
        _capturar_frame(driver, camara_slot, "Paso 2: Formulario completado — iniciando sesión...", modo_camara, 0.5)

        paso_actual = "Presionando botón Iniciar sesión"
        xpath_boton = (
            "//button[contains(text(), 'Iniciar') or contains(text(), 'Acceder') "
            "or contains(text(), 'Log in') or @type='submit'] | //input[@type='submit']"
        )
        boton_ingresar = driver.find_element(By.XPATH, xpath_boton)
        driver.execute_script("arguments[0].click();", boton_ingresar)

        paso_actual = "Esperando ingreso al Área Personal"
        WebDriverWait(driver, 30).until(lambda d: "login" not in d.current_url.lower())
        time.sleep(2.5)
        log_fn("Sesión iniciada correctamente. Leyendo cursos del Área Personal...")
        _capturar_frame(driver, camara_slot, "Paso 3: ¡Dentro de ULagos Virtual! (Área Personal)", modo_camara, 0.7)

        html_dashboard = driver.page_source
        selenium_cookies = driver.get_cookies()

    except Exception as e:
        _capturar_frame(driver, camara_slot, f"Error detectado en: {paso_actual}", True, 0.0)
        url_actual = "Desconocida"
        titulo_pag = "Desconocido"
        try:
            url_actual = driver.current_url
            titulo_pag = driver.title
        except Exception:
            pass
        driver.quit()
        raise RuntimeError(
            f"Fallo en el paso: '{paso_actual}' | URL: {url_actual} | "
            f"Título: {titulo_pag} | Error: {type(e).__name__}"
        ) from e

    sesion = requests.Session()
    for cookie in selenium_cookies:
        sesion.cookies.set(cookie["name"], cookie["value"])
    sesion.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    })

    # Si no se usa cámara ni ventana local, cerramos Chrome de inmediato para ahorrar RAM
    if not modo_camara and not ventana_real:
        driver.quit()
        driver = None

    return driver, sesion, html_dashboard


# --- 2. FUNCIONES DE EXTRACCIÓN (INCLUYE PESTAÑAS TEMA 1, 2, 3, 4) ---
def limpiar_nombre(nombre: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(nombre)).strip()


def obtener_carpeta_ramo(nombre_curso: str, anio_actual: int) -> str:
    mapeo_claves = {
        "Tributaria": f"TRIBUTARIA {anio_actual}",
        "Finanzas": f"FINANZAS AVANZADAS {anio_actual}",
        "Territorial": f"TERRITORIAL {anio_actual}",
        "Proyectos": f"PROYECTOS {anio_actual}",
    }
    for clave, carpeta in mapeo_claves.items():
        if clave.lower() in nombre_curso.lower():
            return carpeta
    return f"{limpiar_nombre(nombre_curso).upper()} {anio_actual}"


def extraer_pestanas_curso(url_curso: str, soup: BeautifulSoup) -> list:
    """Detecta enlaces a secciones y pestañas (Tema 1, Tema 2, Tema 3, Tema 4) del mismo curso."""
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


def descargar_a_zip(sesion, url, archivo_zip, archivos_en_zip, carpeta_ramo, num_archivo, nombre_sugerido=None):
    url_directa = url + "&redirect=1" if "view.php" in url and "redirect=1" not in url else url

    try:
        res = sesion.get(url_directa, verify=False, stream=True, timeout=20)
    except Exception:
        return "ignorados", None

    content_type = res.headers.get("Content-Type", "").lower()

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
                if "pluginfile.php" in href or any(
                    href.endswith(ext) for ext in [".pdf", ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".zip"]
                ):
                    enlace_archivo = a["href"]
                    break

        if enlace_archivo:
            return descargar_a_zip(
                sesion, urljoin(url, enlace_archivo), archivo_zip, archivos_en_zip, carpeta_ramo, num_archivo, titulo_limpio
            )
        return "ignorados", None

    nombre_base = nombre_sugerido if nombre_sugerido else f"apunte_{num_archivo}"
    extension_final = ""

    if "Content-Disposition" in res.headers:
        cd = res.headers["Content-Disposition"]
        if "filename=" in cd:
            nombre_real = cd.split("filename=")[1].strip("\"'").replace('"', "")
            _, ext = os.path.splitext(nombre_real)
            if ext:
                extension_final = ext.lower()
                if not nombre_sugerido:
                    nombre_base = nombre_real.replace(ext, "")

    if not extension_final:
        if "spreadsheet" in content_type or "excel" in content_type:
            extension_final = ".xlsx"
        elif "word" in content_type:
            extension_final = ".docx"
        elif "presentation" in content_type or "powerpoint" in content_type:
            extension_final = ".pptx"
        elif "zip" in content_type:
            extension_final = ".zip"
        else:
            extension_final = ".pdf"

    nombre_archivo = limpiar_nombre(nombre_base) + extension_final
    ruta_interna_zip = f"{carpeta_ramo}/{nombre_archivo}"

    if ruta_interna_zip in archivos_en_zip:
        return "omitidos", nombre_archivo

    archivo_zip.writestr(ruta_interna_zip, res.content)
    archivos_en_zip.add(ruta_interna_zip)
    return "descargados", nombre_archivo


# --- 3. FLUJO EN VIVO ---
if iniciar_btn:
    if not usuario_input or not clave_input:
        st.error("Ingresa tu usuario y contraseña institucional (o configúralos en Streamlit Secrets).")
        st.stop()

    col_cam, col_log = st.columns([1.35, 1.0])
    with col_cam:
        st.markdown("**Monitor en Vivo — Navegador en ULagos Virtual**")
        camara_slot = st.empty()
        if not modo_camara:
            camara_slot.info("Cámara en Vivo desactivada (modo silencioso rápido).")
    with col_log:
        st.markdown("**Consola de Extracción en Tiempo Real**")
        kpi_vivo = st.empty()
        barra_progreso = st.progress(0)
        log_slot = st.empty()

    logs = []
    estadisticas = {"descargados": 0, "omitidos": 0, "ignorados": 0}

    def push_log(msg: str):
        hora = datetime.now().strftime("%H:%M:%S")
        logs.append(f"[{hora}] {msg}")
        log_slot.code("\n".join(logs[-16:]), language="text")

    def refresh_kpi():
        with kpi_vivo.container():
            k1, k2, k3 = st.columns(3)
            k1.metric("Rescatados", estadisticas["descargados"])
            k2.metric("Repetidos", estadisticas["omitidos"])
            k3.metric("Ignorados", estadisticas["ignorados"])

    refresh_kpi()

    driver_activo = None
    try:
        driver_activo, sesion_activa, html_dash = abrir_sesion_con_camara(
            usuario_input,
            dominio_input,
            clave_input,
            camara_slot=camara_slot,
            log_fn=push_log,
            modo_camara=modo_camara,
            ventana_real=modo_ventana_local,
        )
    except Exception as e:
        st.error(f"No fue posible iniciar sesión en ULagos Virtual: {e}")
        st.stop()

    soup_dash = BeautifulSoup(html_dash, "html.parser")
    cursos_dict = {}
    for a in soup_dash.find_all("a", href=True):
        if "course/view.php?id=" in a["href"] and "section=" not in a["href"]:
            nombre = a.text.replace("Haga clic aquí para entrar al curso", "").strip()
            nombre = re.sub(r"\s+", " ", nombre)
            if len(nombre) > 5 and nombre not in cursos_dict.values():
                cursos_dict[a["href"]] = nombre

    if not cursos_dict:
        cursos_dict["https://www.ulagosvirtual.cl/course/view.php?id=4056"] = "Gestión Tributaria (Respaldo)"

    push_log(f"Cursos detectados: {len(cursos_dict)}")
    registro_archivos = []
    archivos_en_zip = set()
    anio_actual = datetime.now().year
    buffer_zip = io.BytesIO()
    total_cursos = len(cursos_dict)

    try:
        with zipfile.ZipFile(buffer_zip, "w", zipfile.ZIP_DEFLATED) as archivo_zip:
            for idx, (url_curso, nombre_curso) in enumerate(cursos_dict.items(), start=1):
                carpeta_destino = obtener_carpeta_ramo(nombre_curso, anio_actual)
                push_log(f"--- Entrando a ({idx}/{total_cursos}): {nombre_curso} ---")

                # Mostrar visualmente en la cámara cuando entra al curso
                if driver_activo is not None and (modo_camara or modo_ventana_local):
                    try:
                        driver_activo.get(url_curso)
                        time.sleep(0.8)
                        _capturar_frame(
                            driver_activo,
                            camara_slot,
                            f"Curso {idx}/{total_cursos}: {nombre_curso}",
                            modo_camara,
                            0.3,
                        )
                        html_curso = driver_activo.page_source
                    except Exception:
                        html_curso = sesion_activa.get(url_curso, verify=False).text
                else:
                    html_curso = sesion_activa.get(url_curso, verify=False).text

                soup = BeautifulSoup(html_curso, "html.parser")
                enlaces_principales = soup.find_all("a", href=True)

                enlaces_directos = list(set([
                    urljoin(url_curso, a["href"]) for a in enlaces_principales
                    if "resource/view.php" in a["href"] or "pluginfile.php" in a["href"] or "url/view.php" in a["href"]
                ]))
                enlaces_carpetas = list(set([
                    urljoin(url_curso, a["href"]) for a in enlaces_principales if "folder/view.php" in a["href"]
                ]))
                enlaces_pestanas = extraer_pestanas_curso(url_curso, soup)

                if enlaces_pestanas:
                    push_log(f"Pestañas / temas detectados en el ramo: {len(enlaces_pestanas)}")

                contador_box = [1]

                def procesar_link(link_objetivo: str):
                    estado, nom = descargar_a_zip(
                        sesion_activa, link_objetivo, archivo_zip, archivos_en_zip, carpeta_destino, contador_box[0]
                    )
                    estadisticas[estado] += 1
                    if estado == "descargados" and nom:
                        registro_archivos.append({"Asignatura": carpeta_destino, "Archivo": nom})
                        push_log(f"[OK] {carpeta_destino}/{nom}")
                        refresh_kpi()
                    contador_box[0] += 1

                for link in enlaces_directos:
                    procesar_link(link)

                for carpeta_url in enlaces_carpetas:
                    try:
                        res_carpeta = sesion_activa.get(carpeta_url, verify=False, timeout=20)
                        archivos_adentro = list(set([
                            urljoin(carpeta_url, a["href"])
                            for a in BeautifulSoup(res_carpeta.text, "html.parser").find_all("a", href=True)
                            if "pluginfile.php" in a["href"] and "forcedownload=1" in a["href"]
                        ]))
                        for link_interno in archivos_adentro:
                            link_limpio = link_interno.split("?")[0] if "?" in link_interno else link_interno
                            procesar_link(link_limpio)
                    except Exception:
                        pass

                for sec_url in enlaces_pestanas:
                    try:
                        res_sec = sesion_activa.get(sec_url, verify=False, timeout=20)
                        soup_sec = BeautifulSoup(res_sec.text, "html.parser")
                        recursos_sec = list(set([
                            urljoin(sec_url, a["href"]) for a in soup_sec.find_all("a", href=True)
                            if "resource/view.php" in a["href"] or "pluginfile.php" in a["href"] or "url/view.php" in a["href"]
                        ]))
                        for link_s in recursos_sec:
                            procesar_link(link_s)
                    except Exception:
                        pass

                barra_progreso.progress(idx / total_cursos)

            fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            texto_reporte = (
                "=========================================\n"
                "  REPORTE EJECUTIVO DE SINCRONIZACIÓN\n"
                "=========================================\n"
                f"Fecha de ejecución: {fecha_actual}\n\n"
                f"[+] Archivos descargados: {estadisticas['descargados']}\n"
                f"[-] Duplicados omitidos: {estadisticas['omitidos']}\n"
                f"[!] Enlaces ignorados: {estadisticas['ignorados']}\n"
                "=========================================\n"
            )
            archivo_zip.writestr("Reporte_Sincronizacion_Ulagos.txt", texto_reporte)
    finally:
        if driver_activo is not None:
            try:
                driver_activo.quit()
            except Exception:
                pass

    refresh_kpi()
    push_log("¡Sincronización completa! Paquete ZIP listo para descargar.")
    st.balloons()
    st.success(f"Extracción terminada: {estadisticas['descargados']} archivos empaquetados.")

    if registro_archivos:
        st.dataframe(pd.DataFrame(registro_archivos), use_container_width=True, hide_index=True)

    st.download_button(
        label=f"Descargar Respaldo Completo (.zip — {estadisticas['descargados']} archivos)",
        data=buffer_zip.getvalue(),
        file_name=f"Respaldo_ULagos_{anio_actual}.zip",
        mime="application/zip",
        use_container_width=True,
    )
