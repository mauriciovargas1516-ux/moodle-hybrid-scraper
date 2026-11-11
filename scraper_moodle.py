import io
import os
import re
import time
import shutil
import zipfile
import urllib3
from datetime import datetime
from urllib.parse import urljoin

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
    layout="centered"
)

st.title("Sincronizador Automatizado de Cursos Moodle")
st.markdown(
    "Herramienta de extracción y respaldo masivo de documentos académicos desde **ULagos Virtual**. "
    "Autentica la sesión, detecta los módulos inscritos y genera un paquete comprimido (`.zip`) "
    "con las carpetas organizadas por asignatura."
)

with st.expander("Guía rápida: ¿Cómo funciona este sincronizador?"):
    st.markdown("""
    * **Acceso directo:** Tus credenciales institucionales ya están precargadas por defecto para ejecutar con un solo clic (puedes editarlas en cualquier momento si necesitas probar otra cuenta).
    * **Detección automática de formatos:** El motor salta los visores incrustados de Moodle y recupera los documentos originales en formato PDF, Excel, Word, PowerPoint o ZIP.
    * **Descarga unificada:** Al finalizar el rastreo, aparecerá un botón para descargar un único archivo `.zip` con todas las carpetas de tus ramos y el reporte ejecutivo de sincronización.
    """)

# --- 1. FORMULARIO CON TUS CREDENCIALES PRECARGADAS ---
with st.form("form_login_moodle"):
    st.subheader("Credenciales de Acceso Institucional")
    col1, col2 = st.columns(2)
    
    with col1:
        usuario_input = st.text_input(
            "Usuario de ULagos",
            value="mauricioalejandro.vargas1",
            help="Primera parte de tu correo institucional, antes del símbolo @."
        )
        dominio_input = st.selectbox(
            "Dominio Institucional",
            options=["@alumnos.ulagos.cl", "@ulagos.cl"],
            index=0,
            help="Dominio correspondiente a tu perfil en ULagos Virtual."
        )
        
    with col2:
        clave_input = st.text_input(
            "Contraseña",
            value="ye16my7re4ij",
            type="password",
            help="Contraseña de acceso a ULagos Virtual."
        )

    iniciar_btn = st.form_submit_button("Iniciar Sincronización y Generar Respaldo", use_container_width=True)


# --- 2. MOTOR DE AUTENTICACIÓN REFORZADO (SSL + IDIOMA + ANTI-BOT) ---
def configurar_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    # Solución al bloqueo por certificado SSL e idioma en servidores de EE. UU.
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


def obtener_sesion_hibrida(usuario, dominio, clave):
    driver = configurar_driver()
    paso_actual = "Abriendo portal ULagos Virtual"
    try:
        driver.set_page_load_timeout(35)
        driver.get(URL_LOGIN)

        # Esperar que cargue la casilla de usuario (soporta español, inglés o genérico)
        paso_actual = "Buscando casilla de Usuario en la página de login"
        xpath_usuario = (
            "//input[@placeholder='Usuario' or @placeholder='Username' "
            "or @name='username' or @id='username' or @type='text']"
        )
        caja_usuario = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, xpath_usuario))
        )
        caja_usuario.clear()
        caja_usuario.send_keys(usuario.strip())

        # Seleccionar el dominio si existe el menú desplegable <select>
        paso_actual = "Seleccionando dominio institucional (@alumnos.ulagos.cl)"
        selects = driver.find_elements(By.XPATH, "//select")
        if selects:
            menu_desplegable = Select(selects[0])
            try:
                menu_desplegable.select_by_visible_text(dominio)
            except Exception:
                # Si no coincide el texto exacto, busca por valor parcial
                for opt in menu_desplegable.options:
                    if dominio in opt.text or dominio in (opt.get_attribute("value") or ""):
                        opt.click()
                        break

        # Llenar contraseña
        paso_actual = "Ingresando contraseña"
        xpath_clave = "//input[@placeholder='Contraseña' or @placeholder='Password' or @type='password']"
        caja_clave = driver.find_element(By.XPATH, xpath_clave)
        caja_clave.clear()
        caja_clave.send_keys(clave)

        # Hacer clic en el botón de ingreso mediante JavaScript para evitar bloqueos visuales
        paso_actual = "Presionando botón Iniciar sesión"
        xpath_boton = (
            "//button[contains(text(), 'Iniciar') or contains(text(), 'Acceder') "
            "or contains(text(), 'Log in') or @type='submit'] | //input[@type='submit']"
        )
        boton_ingresar = driver.find_element(By.XPATH, xpath_boton)
        driver.execute_script("arguments[0].click();", boton_ingresar)

        # Esperar redirección fuera del login
        paso_actual = "Esperando validación de credenciales y redirección al Área Personal"
        WebDriverWait(driver, 30).until(lambda d: "login" not in d.current_url.lower())
        time.sleep(3)

        html_dashboard = driver.page_source
        selenium_cookies = driver.get_cookies()

    except Exception as e:
        # Capturar diagnóstico visual de lo que ve el servidor en ese instante
        captura_error = None
        url_actual = "Desconocida"
        titulo_pag = "Desconocido"
        try:
            captura_error = driver.get_screenshot_as_png()
            url_actual = driver.current_url
            titulo_pag = driver.title
        except Exception:
            pass
        driver.quit()
        raise RuntimeError(
            f"Fallo en el paso: '{paso_actual}' | URL cargada: {url_actual} | "
            f"Título de página: {titulo_pag} | Error original: {type(e).__name__}"
        ) from e

    driver.quit()

    sesion = requests.Session()
    for cookie in selenium_cookies:
        sesion.cookies.set(cookie["name"], cookie["value"])
    sesion.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    })

    return sesion, html_dashboard


# --- 3. FUNCIONES DE EXTRACCIÓN Y EMPAQUETADO EN MEMORIA ---
def limpiar_nombre(nombre):
    return re.sub(r'[\\/*?:"<>|]', "", nombre).strip()


def obtener_carpeta_ramo(nombre_curso, año_actual):
    mapeo_claves = {
        "Tributaria": f"TRIBUTARIA {año_actual}",
        "Finanzas": f"FINANZAS AVANZADAS {año_actual}",
        "Territorial": f"TERRITORIAL {año_actual}",
        "Proyectos": f"PROYECTOS {año_actual}"
    }
    for clave, carpeta in mapeo_claves.items():
        if clave.lower() in nombre_curso.lower():
            return carpeta
    return f"{limpiar_nombre(nombre_curso).upper()} {año_actual}"


def descargar_a_zip(sesion, url, archivo_zip, archivos_en_zip, carpeta_ramo, num_archivo, nombre_sugerido=None):
    url_directa = url + "&redirect=1" if "view.php" in url else url

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
        else:
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
        elif "zip" in content_type:
            extension_final = ".zip"
        else:
            extension_final = ".pdf"

    nombre_archivo = limpiar_nombre(nombre_base) + extension_final
    ruta_interna_zip = f"{carpeta_ramo}/{nombre_archivo}"

    if ruta_interna_zip in archivos_en_zip:
        return "omitidos", nombre_archivo

    contenido_bytes = res.content
    archivo_zip.writestr(ruta_interna_zip, contenido_bytes)
    archivos_en_zip.add(ruta_interna_zip)

    return "descargados", nombre_archivo


# --- 4. FLUJO PRINCIPAL EN STREAMLIT ---
if iniciar_btn:
    if not usuario_input or not clave_input:
        st.error("Por favor, ingresa tu usuario y contraseña institucional antes de continuar.")
    else:
        with st.status("Ejecutando sincronización con ULagos Virtual...", expanded=True) as status_box:
            st.write("Iniciando sesión automatizada y validando credenciales...")
            try:
                sesion_activa, html_dash = obtener_sesion_hibrida(usuario_input, dominio_input, clave_input)
            except Exception as e:
                status_box.update(label="Error de autenticación", state="error", expanded=True)
                st.error(f"No fue posible completar el inicio de sesión. Detalle de diagnóstico: {e}")
                st.stop()

            st.write("Analizando cursos disponibles en tu Área Personal...")
            soup_dash = BeautifulSoup(html_dash, "html.parser")
            cursos_dict = {}
            for a in soup_dash.find_all("a", href=True):
                if "course/view.php?id=" in a["href"]:
                    nombre = a.text.replace("Haga clic aquí para entrar al curso", "").strip()
                    nombre = re.sub(r"\s+", " ", nombre)
                    if len(nombre) > 5 and nombre not in cursos_dict.values():
                        cursos_dict[a["href"]] = nombre

            if not cursos_dict:
                cursos_dict["https://www.ulagosvirtual.cl/course/view.php?id=4056"] = "Gestión Tributaria (Respaldo)"

            estadisticas = {"descargados": 0, "omitidos": 0, "ignorados": 0}
            registro_archivos = []
            archivos_en_zip = set()
            año_actual = datetime.now().year

            buffer_zip = io.BytesIO()
            barra_progreso = st.progress(0)
            total_cursos = len(cursos_dict)

            with zipfile.ZipFile(buffer_zip, "w", zipfile.ZIP_DEFLATED) as archivo_zip:
                for idx, (url_curso, nombre_curso) in enumerate(cursos_dict.items(), start=1):
                    carpeta_destino = obtener_carpeta_ramo(nombre_curso, año_actual)
                    st.write(f"Sincronizando módulo ({idx}/{total_cursos}): **{nombre_curso}**")

                    response = sesion_activa.get(url_curso, verify=False)
                    soup = BeautifulSoup(response.text, "html.parser")
                    enlaces_principales = soup.find_all("a", href=True)

                    enlaces_directos = list(set([
                        a["href"] for a in enlaces_principales
                        if "resource/view.php" in a["href"] or "pluginfile.php" in a["href"] or "url/view.php" in a["href"]
                    ]))
                    enlaces_carpetas = list(set([
                        a["href"] for a in enlaces_principales if "folder/view.php" in a["href"]
                    ]))
                    enlaces_secciones = list(set([
                        a["href"] for a in enlaces_principales if "course/section.php" in a["href"]
                    ]))

                    contador = 1

                    for link in enlaces_directos:
                        estado, nom = descargar_a_zip(
                            sesion_activa, link, archivo_zip, archivos_en_zip, carpeta_destino, contador
                        )
                        estadisticas[estado] += 1
                        if estado == "descargados" and nom:
                            registro_archivos.append({"Asignatura": carpeta_destino, "Archivo": nom})
                        contador += 1

                    for carpeta_url in enlaces_carpetas:
                        res_carpeta = sesion_activa.get(carpeta_url, verify=False)
                        archivos_adentro = list(set([
                            a["href"] for a in BeautifulSoup(res_carpeta.text, "html.parser").find_all("a", href=True)
                            if "pluginfile.php" in a["href"] and "forcedownload=1" in a["href"]
                        ]))
                        for link_interno in archivos_adentro:
                            link_limpio = (
                                link_interno.split("?")[0]
                                if "?" in link_interno and "pluginfile" in link_interno
                                else link_interno
                            )
                            estado, nom = descargar_a_zip(
                                sesion_activa, link_limpio, archivo_zip, archivos_en_zip, carpeta_destino, contador
                            )
                            estadisticas[estado] += 1
                            if estado == "descargados" and nom:
                                registro_archivos.append({"Asignatura": carpeta_destino, "Archivo": nom})
                            contador += 1

                    for seccion_url in enlaces_secciones:
                        res_seccion = sesion_activa.get(seccion_url, verify=False)
                        recursos_seccion = list(set([
                            a["href"] for a in BeautifulSoup(res_seccion.text, "html.parser").find_all("a", href=True)
                            if "resource/view.php" in a["href"] or "pluginfile.php" in a["href"] or "url/view.php" in a["href"]
                        ]))
                        for link in recursos_seccion:
                            estado, nom = descargar_a_zip(
                                sesion_activa, link, archivo_zip, archivos_en_zip, carpeta_destino, contador
                            )
                            estadisticas[estado] += 1
                            if estado == "descargados" and nom:
                                registro_archivos.append({"Asignatura": carpeta_destino, "Archivo": nom})
                            contador += 1

                    barra_progreso.progress(idx / total_cursos)

                fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                texto_reporte = (
                    "=========================================\n"
                    "  REPORTE EJECUTIVO DE SINCRONIZACIÓN\n"
                    "=========================================\n"
                    f"Fecha de ejecución: {fecha_actual}\n\n"
                    "RESUMEN GLOBAL:\n"
                    f"[+] Archivos descargados: {estadisticas['descargados']}\n"
                    f"[-] Archivos duplicados omitidos: {estadisticas['omitidos']}\n"
                    f"[!] Enlaces externos ignorados: {estadisticas['ignorados']}\n\n"
                    "ESTADO: Sincronización completada correctamente.\n"
                    "=========================================\n"
                )
                archivo_zip.writestr("Reporte_Sincronizacion_Ulagos.txt", texto_reporte)

            status_box.update(label="Sincronización finalizada correctamente", state="complete", expanded=False)

        # --- 5. RESULTADOS Y DESCARGA DEL PAQUETE ---
        st.subheader("Resumen de Sincronización")
        m1, m2, m3 = st.columns(3)
        m1.metric(
            "Archivos Rescatados",
            estadisticas["descargados"],
            help="Total de documentos válidos (PDF, Excel, Word, etc.) extraídos y guardados dentro del archivo ZIP."
        )
        m2.metric(
            "Duplicados Omitidos",
            estadisticas["omitidos"],
            help="Archivos que estaban repetidos en más de una sección del mismo curso y se guardaron una sola vez."
        )
        m3.metric(
            "Enlaces Externos Ignorados",
            estadisticas["ignorados"],
            help="Vínculos a páginas web externas o foros que no contienen documentos descargables."
        )

        if registro_archivos:
            st.dataframe(pd.DataFrame(registro_archivos), use_container_width=True, hide_index=True)

        st.download_button(
            label="Descargar Todas las Carpetas y Reporte (.zip)",
            data=buffer_zip.getvalue(),
            file_name=f"Respaldo_ULagos_{año_actual}.zip",
            mime="application/zip",
            use_container_width=True
        )
