# -*- coding: utf-8 -*-
import html
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
    page_title="ULAGOS://NET-SYNC — Sincronizador Moodle",
    layout="wide",
)


def _leer_secreto(clave: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(clave, default))
    except Exception:
        return default


# --- SELECTOR DE ESTILO VISUAL EN BARRA LATERAL ---
with st.sidebar:
    st.markdown("### Centro de Control")
    modo_hacker = st.toggle("Modo Hacker / Flujo Cyber", value=True)
    st.caption(
        "Muestra el mapa de flujo animado entre ULagos Virtual, el motor híbrido y tus 4 repositorios."
    )

if modo_hacker:
    st.markdown(
        """
        <style>
        .stApp, [data-testid="stAppViewContainer"] {
            background-color: #05090E !important;
            color: #D1FAE5 !important;
        }
        [data-testid="stHeader"] {
            background-color: #05090E !important;
        }
        [data-testid="stSidebar"] {
            background-color: #09111A !important;
            border-right: 1px solid #0F3D2E !important;
        }
        h1, h2, h3, .stMarkdown p, label {
            color: #D1FAE5 !important;
        }
        div[data-testid="stMetric"] {
            background-color: #0B1520 !important;
            border: 1px solid #00FF41 !important;
            border-radius: 6px !important;
            padding: 10px 12px !important;
            box-shadow: 0 0 10px rgba(0, 255, 65, 0.14);
        }
        div[data-testid="stMetricValue"] {
            color: #00FF41 !important;
            font-family: Consolas, "Courier New", monospace !important;
        }
        div[data-testid="stForm"] {
            background-color: #0A131D !important;
            border: 1px solid #164E63 !important;
            border-radius: 8px !important;
        }
        .stTextInput input, .stSelectbox div[data-baseweb="select"] {
            background-color: #060C12 !important;
            color: #00FF41 !important;
            border-color: #155E75 !important;
            font-family: Consolas, "Courier New", monospace !important;
        }
        .stButton button, .stDownloadButton button, div[data-testid="stFormSubmitButton"] button {
            background-color: #06281E !important;
            color: #00FF41 !important;
            border: 1px solid #00FF41 !important;
            font-family: Consolas, "Courier New", monospace !important;
            font-weight: 700 !important;
        }
        .stButton button:hover, .stDownloadButton button:hover, div[data-testid="stFormSubmitButton"] button:hover {
            background-color: #00FF41 !important;
            color: #05090E !important;
        }
        pre, code {
            background-color: #03070B !important;
            color: #00FF41 !important;
            border: 1px solid #0F3D2E !important;
        }
        .cyber-banner {
            background: linear-gradient(90deg, #040B11 0%, #071E26 55%, #052E16 100%);
            border: 1px solid #00FF41;
            border-left: 5px solid #00F0FF;
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 14px;
            font-family: Consolas, "Courier New", monospace;
            box-shadow: 0 0 18px rgba(0, 255, 65, 0.15);
        }
        .cyber-title {
            font-size: 20px;
            font-weight: 800;
            color: #00FF41;
            letter-spacing: 0.8px;
        }
        .cyber-sub {
            font-size: 12px;
            color: #67E8F9;
            margin-top: 4px;
        }
        </style>
        <div class="cyber-banner">
            <div class="cyber-title">&gt;_ ULAGOS://NET-SYNC v2.6 [ROBOT HÍBRIDO + FLUJO EN VIVO]</div>
            <div class="cyber-sub">ENLACE ACTIVO: ULAGOS VIRTUAL (MOODLE) &rarr; MOTOR SELENIUM/REQUESTS &rarr; GITHUB REPOS (TRIBUTARIA · TERRITORIAL · FINANZAS · PROYECTOS)</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.title("Sincronizador Automatizado de Cursos Moodle")
    st.markdown(
        "Extrae y empaqueta tus apuntes desde **ULagos Virtual** en un `.zip` organizado por ramo, "
        "con mapa de flujo visual y **Cámara en Vivo**."
    )


def render_svg_flujo_red(
    fase: str = "STANDBY",
    ramo_activo: str = "",
    conteos: dict = None,
    ultimo_archivo: str = "",
    hacker: bool = True,
) -> str:
    """
    Genera un diagrama SVG animado (SMIL nativo) mostrando el flujo de datos:
    ULagos Virtual -> Motor Híbrido -> 4 Repositorios de Ramos + ZIP.
    """
    conteos = conteos or {}
    bg = "#060D14" if hacker else "#F8FAFC"
    border_main = "#0F3D2E" if hacker else "#CBD5E1"
    node_bg = "#0B1622" if hacker else "#FFFFFF"
    txt_pri = "#E2FBE8" if hacker else "#0F172A"
    txt_sec = "#67E8F9" if hacker else "#475569"
    c_idle = "#1E3A4C" if hacker else "#CBD5E1"
    c_neon = "#00FF41" if hacker else "#16A34A"
    c_cyan = "#00F0FF" if hacker else "#2563EB"
    c_warn = "#FACC15" if hacker else "#D97706"

    fase_up = fase.upper()
    en_login = fase_up in ("AUTH", "SCAN", "SYNC", "DONE")
    en_scan = fase_up in ("SCAN", "SYNC", "DONE")
    en_sync = fase_up in ("SYNC", "DONE")

    col_pipe_1 = c_neon if en_login else c_idle
    col_moodle = c_neon if en_login else c_cyan
    col_motor = c_neon if en_scan else (c_warn if fase_up == "AUTH" else c_cyan)

    nodos_destino = [
        ("TRIBUTARIA", "GESTION-TRIBUTARIA-2026", 44),
        ("TERRITORIAL", "TERRITORIAL-2026", 104),
        ("FINANZAS", "FINANZAS-AVANZADAS-2026", 164),
        ("PROYECTOS", "PROYECTOS-2026", 224),
    ]

    pipes_svg = []
    # Tubería principal Moodle -> Motor
    pipes_svg.append(
        f'<line x1="215" y1="134" x2="345" y2="134" stroke="{col_pipe_1}" stroke-width="3" '
        f'stroke-dasharray="8 6">'
        + (
            '<animate attributeName="stroke-dashoffset" from="28" to="0" dur="0.7s" repeatCount="indefinite" />'
            if en_login
            else ""
        )
        + "</line>"
    )
    if en_login:
        pipes_svg.append(
            f'<circle r="4.5" fill="{c_cyan}">'
            '<animate attributeName="cx" from="215" to="345" dur="0.9s" repeatCount="indefinite" />'
            '<animate attributeName="cy" values="134;134" dur="0.9s" repeatCount="indefinite" />'
            "</circle>"
        )

    dest_svg = []
    for clave, etiqueta, y_pos in nodos_destino:
        cnt = int(conteos.get(clave, 0))
        es_activo = (clave in ramo_activo.upper()) or (fase_up == "DONE" and cnt > 0)
        col_n = c_neon if es_activo else (c_cyan if cnt > 0 else c_idle)
        sw = "2.6" if es_activo else "1.6"

        # Curva Bezier desde Motor (555, 134) hasta cada nodo (675, y_pos)
        d_path = f"M 555 134 C 615 134, 615 {y_pos}, 675 {y_pos}"
        anim_line = (
            '<animate attributeName="stroke-dashoffset" from="24" to="0" dur="0.65s" repeatCount="indefinite" />'
            if es_activo
            else ""
        )
        pipes_svg.append(
            f'<path id="p_{clave}" d="{d_path}" fill="none" stroke="{col_n}" stroke-width="{sw}" '
            f'stroke-dasharray="7 5">{anim_line}</path>'
        )
        if es_activo and fase_up == "SYNC":
            pipes_svg.append(
                f'<circle r="4.2" fill="{c_neon}">'
                f'<animateMotion dur="0.8s" repeatCount="indefinite" path="{d_path}" />'
                "</circle>"
            )

        badge_txt = f"{cnt} arch." if cnt > 0 else ("SYNC..." if es_activo else "EN ESPERA")
        dest_svg.append(
            f'<rect x="675" y="{y_pos - 22}" width="265" height="44" rx="7" fill="{node_bg}" stroke="{col_n}" stroke-width="{sw}" />'
            f'<circle cx="693" cy="{y_pos}" r="5" fill="{col_n}" />'
            f'<text x="706" y="{y_pos - 3}" fill="{txt_pri}" font-family="Consolas, monospace" font-size="11.5" font-weight="700">{etiqueta}</text>'
            f'<text x="706" y="{y_pos + 13}" fill="{txt_sec}" font-family="Consolas, monospace" font-size="10">apuntes_moodle/ · {badge_txt}</text>'
        )

    estado_lbl = {
        "STANDBY": "LISTO PARA INICIAR TRANSMISIÓN",
        "AUTH": "AUTENTICANDO EN ULAGOS VIRTUAL...",
        "SCAN": "ESCANEANDO CURSOS Y PESTAÑAS...",
        "SYNC": f"TRANSFIRIENDO PAQUETES -> {ramo_activo or 'CURSOS'}",
        "DONE": "SINCRONIZACIÓN COMPLETADA · 100% OK",
    }.get(fase_up, fase_up)

    ult_clean = (ultimo_archivo[:64] + "...") if len(ultimo_archivo) > 64 else ultimo_archivo
    if not ult_clean:
        ult_clean = "Esperando pulso de sincronización o reporte de GitHub Actions..."
    ult_clean = html.escape(ult_clean)
    estado_lbl = html.escape(estado_lbl)

    svg = f"""
<svg viewBox="0 0 960 285" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;border-radius:8px;border:1px solid {border_main};background:{bg};">
  <defs>
    <pattern id="gridbg" width="24" height="24" patternUnits="userSpaceOnUse">
      <path d="M 24 0 L 0 0 0 24" fill="none" stroke="{border_main}" stroke-width="0.6" opacity="0.45"/>
    </pattern>
  </defs>
  <rect width="960" height="285" fill="{bg}" />
  <rect width="960" height="285" fill="url(#gridbg)" />

  <!-- Encabezado telemetría -->
  <text x="18" y="21" fill="{c_neon}" font-family="Consolas, monospace" font-size="11" font-weight="700">STATUS: {estado_lbl}</text>
  <text x="942" y="21" text-anchor="end" fill="{txt_sec}" font-family="Consolas, monospace" font-size="10.5">PIPELINE: MOODLE -&gt; HYBRID ENGINE -&gt; REPOS</text>

  {''.join(pipes_svg)}

  <!-- Nodo 1: ULagos Virtual -->
  <rect x="20" y="84" width="195" height="100" rx="9" fill="{node_bg}" stroke="{col_moodle}" stroke-width="2.4" />
  <circle cx="38" cy="105" r="5.5" fill="{col_moodle}">
    <animate attributeName="opacity" values="1;0.3;1" dur="1.4s" repeatCount="indefinite" />
  </circle>
  <text x="50" y="109" fill="{txt_pri}" font-family="Consolas, monospace" font-size="12.5" font-weight="700">ULAGOS VIRTUAL</text>
  <text x="34" y="132" fill="{txt_sec}" font-family="Consolas, monospace" font-size="10">Portal Moodle LMS</text>
  <text x="34" y="149" fill="{txt_sec}" font-family="Consolas, monospace" font-size="10">Tema 1..4 + Carpetas</text>
  <text x="34" y="168" fill="{c_neon}" font-family="Consolas, monospace" font-size="10">HTTPS // PORT 443</text>

  <!-- Nodo 2: Motor Híbrido -->
  <rect x="345" y="76" width="210" height="116" rx="9" fill="{node_bg}" stroke="{col_motor}" stroke-width="2.6" />
  <circle cx="364" cy="98" r="5.5" fill="{col_motor}">
    <animate attributeName="opacity" values="1;0.25;1" dur="1.0s" repeatCount="indefinite" />
  </circle>
  <text x="376" y="102" fill="{txt_pri}" font-family="Consolas, monospace" font-size="12.5" font-weight="700">MOTOR HÍBRIDO</text>
  <text x="360" y="124" fill="{txt_sec}" font-family="Consolas, monospace" font-size="10">1. Selenium Auth Hijack</text>
  <text x="360" y="141" fill="{txt_sec}" font-family="Consolas, monospace" font-size="10">2. Requests Bypass PDF</text>
  <text x="360" y="158" fill="{txt_sec}" font-family="Consolas, monospace" font-size="10">3. SHA-1 Dedup + ZIP</text>
  <text x="360" y="177" fill="{c_cyan}" font-family="Consolas, monospace" font-size="10">ROBOT CRON: 08:00 / 20:00</text>

  <!-- Nodos 3: 4 Repositorios -->
  {''.join(dest_svg)}

  <!-- Pie telemetría -->
  <rect x="20" y="253" width="920" height="22" rx="4" fill="{node_bg}" stroke="{border_main}" stroke-width="1" />
  <text x="32" y="268" fill="{c_neon}" font-family="Consolas, monospace" font-size="10.5">&gt; {ult_clean}</text>
</svg>
"""
    return svg


def _conteos_desde_reporte(rep: dict) -> dict:
    out = {"TRIBUTARIA": 0, "TERRITORIAL": 0, "FINANZAS": 0, "PROYECTOS": 0}
    for k, v in rep.get("repos", {}).items():
        ku = k.upper()
        for cl in out:
            if cl in ku:
                out[cl] += int(v.get("total_detectados", 0))
    return out


# --- PANEL SUPERIOR: MAPA DE FLUJO EN VIVO + ESTADO DEL ROBOT GITHUB ACTIONS ---
rep_robot = None
if os.path.exists("ultimo_sync.json"):
    try:
        with open("ultimo_sync.json", "r", encoding="utf-8") as _fj:
            rep_robot = json.load(_fj)
    except Exception:
        rep_robot = None

flujo_slot = st.empty()
if rep_robot:
    _cnt_init = _conteos_desde_reporte(rep_robot)
    _ult_nov = rep_robot["novedades"][0] if rep_robot.get("novedades") else f"Última corrida automática: {rep_robot.get('fecha_chile', 'N/D')} ({rep_robot.get('estado', 'OK')})"
    flujo_slot.markdown(
        render_svg_flujo_red(
            fase="DONE" if rep_robot.get("estado") == "OK" else "STANDBY",
            conteos=_cnt_init,
            ultimo_archivo=_ult_nov,
            hacker=modo_hacker,
        ),
        unsafe_allow_html=True,
    )
else:
    flujo_slot.markdown(
        render_svg_flujo_red(fase="STANDBY", hacker=modo_hacker),
        unsafe_allow_html=True,
    )

if rep_robot:
    with st.expander(
        f"Robot Automático GitHub Actions — Última corrida: {rep_robot.get('fecha_chile', 'N/D')} ({rep_robot.get('estado', 'N/D')})",
        expanded=False,
    ):
        _res = rep_robot.get("resumen", {})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cursos revisados", _res.get("cursos_revisados", 0))
        c2.metric("Nuevos subidos", _res.get("nuevos_subidos", 0))
        c3.metric("Sin cambios", _res.get("sin_cambios", 0))
        c4.metric("Multi-repo activo", "Sí" if rep_robot.get("push_multirepo_activo") else "Pendiente PAT")
        if rep_robot.get("nota"):
            st.info(rep_robot["nota"])
        if rep_robot.get("novedades"):
            st.markdown("**Últimos archivos enviados a tus repositorios:**")
            st.code("\n".join(rep_robot["novedades"][:12]), language="text")
        _repos_dict = rep_robot.get("repos", {})
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

# --- FORMULARIO DE EJECUCIÓN EN VIVO ---
user_default = _leer_secreto("MOODLE_USER", "")
pass_default = _leer_secreto("MOODLE_PASS", "")

with st.form("form_login_moodle"):
    st.subheader("Consola de Acceso Manual (Ejecución en Vivo)")
    col1, col2 = st.columns(2)

    with col1:
        usuario_input = st.text_input(
            "Usuario de ULagos",
            value=user_default,
            placeholder="ej. nombre.apellido",
            help="Primera parte de tu correo institucional, antes del @. Opcional: guarda MOODLE_USER en Streamlit Secrets.",
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
            help="Opcional: guarda MOODLE_PASS en Streamlit Secrets para no escribirla cada vez.",
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

    iniciar_btn = st.form_submit_button(">_ LANZAR SINCRONIZACIÓN EN VIVO", use_container_width=True)


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
        log_fn("[INIT] Desplegando Chromium headless -> ulagosvirtual.cl ...")
        driver.get(URL_LOGIN)
        time.sleep(1.0)
        _capturar_frame(driver, camara_slot, "[CAM 01] Portal de acceso ULagos Virtual interceptado", modo_camara, 0.5)

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
        log_fn(f"[AUTH] Inyectando credenciales ({usuario.strip()}{dominio})...")
        _capturar_frame(driver, camara_slot, "[CAM 02] Credenciales cargadas — ejecutando login...", modo_camara, 0.5)

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
        log_fn("[OK] Sesión autorizada. Capturando cookie MoodleSession...")
        _capturar_frame(driver, camara_slot, "[CAM 03] ACCESO CONCEDIDO — Área Personal ULagos", modo_camara, 0.7)

        html_dashboard = driver.page_source
        selenium_cookies = driver.get_cookies()

    except Exception as e:
        _capturar_frame(driver, camara_slot, f"[ERROR] Fallo en: {paso_actual}", True, 0.0)
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

    if not modo_camara and not ventana_real:
        driver.quit()
        driver = None

    return driver, sesion, html_dashboard


# --- 2. FUNCIONES DE EXTRACCIÓN ---
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


def extraer_clave_ramo_svg(carpeta_destino: str) -> str:
    up = carpeta_destino.upper()
    for cl in ("TRIBUTARIA", "TERRITORIAL", "FINANZAS", "PROYECTOS"):
        if cl in up:
            return cl
    return ""


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

    conteos_svg = {"TRIBUTARIA": 0, "TERRITORIAL": 0, "FINANZAS": 0, "PROYECTOS": 0}
    flujo_slot.markdown(
        render_svg_flujo_red(fase="AUTH", conteos=conteos_svg, ultimo_archivo="Estableciendo túnel HTTPS con ulagosvirtual.cl...", hacker=modo_hacker),
        unsafe_allow_html=True,
    )

    col_cam, col_log = st.columns([1.3, 1.0])
    with col_cam:
        st.markdown("**[FEED EN VIVO] Cámara del Navegador en ULagos Virtual**")
        camara_slot = st.empty()
        if not modo_camara:
            camara_slot.info("Cámara en Vivo desactivada (modo silencioso rápido).")
    with col_log:
        st.markdown("**[TERMINAL] Consola de Paquetes y Extracción**")
        kpi_vivo = st.empty()
        barra_progreso = st.progress(0)
        log_slot = st.empty()

    logs = []
    estadisticas = {"descargados": 0, "omitidos": 0, "ignorados": 0}

    def push_log(msg: str):
        hora = datetime.now().strftime("%H:%M:%S")
        logs.append(f"root@ulagos-sync [{hora}]$ {msg}")
        log_slot.code("\n".join(logs[-16:]), language="bash")

    def refresh_kpi():
        with kpi_vivo.container():
            k1, k2, k3 = st.columns(3)
            k1.metric("Paquetes OK", estadisticas["descargados"])
            k2.metric("Duplicados", estadisticas["omitidos"])
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
        flujo_slot.markdown(
            render_svg_flujo_red(fase="STANDBY", conteos=conteos_svg, ultimo_archivo=f"ERROR AUTH: {e}", hacker=modo_hacker),
            unsafe_allow_html=True,
        )
        st.error(f"No fue posible iniciar sesión en ULagos Virtual: {e}")
        st.stop()

    flujo_slot.markdown(
        render_svg_flujo_red(fase="SCAN", conteos=conteos_svg, ultimo_archivo="Sesión activa. Mapeando cursos inscritos...", hacker=modo_hacker),
        unsafe_allow_html=True,
    )

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

    push_log(f"[SCAN] {len(cursos_dict)} nodos de asignatura detectados.")
    registro_archivos = []
    archivos_en_zip = set()
    anio_actual = datetime.now().year
    buffer_zip = io.BytesIO()
    total_cursos = len(cursos_dict)

    try:
        with zipfile.ZipFile(buffer_zip, "w", zipfile.ZIP_DEFLATED) as archivo_zip:
            for idx, (url_curso, nombre_curso) in enumerate(cursos_dict.items(), start=1):
                carpeta_destino = obtener_carpeta_ramo(nombre_curso, anio_actual)
                clave_svg = extraer_clave_ramo_svg(carpeta_destino)
                push_log(f"[NODE {idx}/{total_cursos}] Infiltrando -> {nombre_curso}")

                flujo_slot.markdown(
                    render_svg_flujo_red(
                        fase="SYNC",
                        ramo_activo=clave_svg or nombre_curso,
                        conteos=conteos_svg,
                        ultimo_archivo=f"Escaneando {nombre_curso}...",
                        hacker=modo_hacker,
                    ),
                    unsafe_allow_html=True,
                )

                if driver_activo is not None and (modo_camara or modo_ventana_local):
                    try:
                        driver_activo.get(url_curso)
                        time.sleep(0.8)
                        _capturar_frame(
                            driver_activo,
                            camara_slot,
                            f"[CAM NODE {idx}/{total_cursos}] {nombre_curso}",
                            modo_camara,
                            0.25,
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
                    push_log(f"[TABS] {len(enlaces_pestanas)} pestañas/temas detectados.")

                contador_box = [1]

                def procesar_link(link_objetivo: str):
                    estado, nom = descargar_a_zip(
                        sesion_activa, link_objetivo, archivo_zip, archivos_en_zip, carpeta_destino, contador_box[0]
                    )
                    estadisticas[estado] += 1
                    if estado == "descargados" and nom:
                        registro_archivos.append({"Asignatura": carpeta_destino, "Archivo": nom})
                        if clave_svg in conteos_svg:
                            conteos_svg[clave_svg] += 1
                        push_log(f"[GET OK] {carpeta_destino}/{nom}")
                        refresh_kpi()
                        flujo_slot.markdown(
                            render_svg_flujo_red(
                                fase="SYNC",
                                ramo_activo=clave_svg or nombre_curso,
                                conteos=conteos_svg,
                                ultimo_archivo=f"[OK] {carpeta_destino}/{nom}",
                                hacker=modo_hacker,
                            ),
                            unsafe_allow_html=True,
                        )
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
    push_log(f"[DONE] Transmisión finalizada: {estadisticas['descargados']} archivos empaquetados.")
    flujo_slot.markdown(
        render_svg_flujo_red(
            fase="DONE",
            conteos=conteos_svg,
            ultimo_archivo=f"Paquete listo: {estadisticas['descargados']} archivos rescatados.",
            hacker=modo_hacker,
        ),
        unsafe_allow_html=True,
    )
    st.balloons()
    st.success(f"Extracción terminada: {estadisticas['descargados']} archivos empaquetados.")

    if registro_archivos:
        st.dataframe(pd.DataFrame(registro_archivos), use_container_width=True, hide_index=True)

    st.download_button(
        label=f">_ DESCARGAR PAQUETE COMPLETO (.zip — {estadisticas['descargados']} archivos)",
        data=buffer_zip.getvalue(),
        file_name=f"Respaldo_ULagos_{anio_actual}.zip",
        mime="application/zip",
        use_container_width=True,
    )
