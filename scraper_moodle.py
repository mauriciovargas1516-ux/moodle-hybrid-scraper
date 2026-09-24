import requests
from bs4 import BeautifulSoup
import os
import re
import urllib3
from urllib.parse import urljoin
import time
from datetime import datetime

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import Select
except ImportError:
    print("Falta instalar Selenium. Ejecuta en la terminal: pip install selenium")
    exit()

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. CREDENCIALES ---
URL_LOGIN = "https://www.ulagosvirtual.cl/login/index.php"

# --- 2. MOTOR DE AUTENTICACIÓN AVANZADO (SELENIUM) ---
def obtener_sesion_hibrida():
    print("Abriendo Chrome automatizado...")
    options = webdriver.ChromeOptions()
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    # Opcional: Descomenta la siguiente línea si quieres que se ejecute invisible en el fondo
    # options.add_argument('--headless') 
    
    driver = webdriver.Chrome(options=options)
    # Entramos directamente al link que mencionaste
    driver.get("https://www.ulagosvirtual.cl/login/index.php")
    
    print("Iniciando sesión automáticamente...")
    
    try:
        # 1. Esperamos y llenamos la caja "Usuario"
        caja_usuario = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Usuario']"))
        )
        caja_usuario.send_keys("mauricioalejandro.vargas1")
        
        # 2. Seleccionamos el dominio "@alumnos.ulagos.cl" en el desplegable
        # Buscamos el elemento <select> que está en ese formulario
        elemento_select = driver.find_element(By.XPATH, "//select")
        menu_desplegable = Select(elemento_select)
        menu_desplegable.select_by_visible_text("@alumnos.ulagos.cl")
        
        # 3. Llenamos la caja "Contraseña"
        caja_clave = driver.find_element(By.XPATH, "//input[@placeholder='Contraseña']")
        caja_clave.send_keys("ye16my7re4ij")
        
        # 4. Hacemos clic en el botón "Iniciar sesión"
        boton_ingresar = driver.find_element(By.XPATH, "//button[contains(text(), 'Iniciar sesión')]")
        boton_ingresar.click()
        
    except Exception as e:
        print("Error al intentar llenar las 3 casillas. Verifica si cambió el diseño de la página:", e)

    print("Esperando acceso al Área Personal...")
    
    WebDriverWait(driver, 120).until(lambda d: "login" not in d.current_url.lower())
    
    print("¡Acceso concedido automáticamente! Esperando que Moodle dibuje los cursos...")
    time.sleep(4) 
    
    html_dashboard = driver.page_source
    selenium_cookies = driver.get_cookies()
    driver.quit() 
    
    sesion = requests.Session()
    for cookie in selenium_cookies:
        sesion.cookies.set(cookie['name'], cookie['value'])
    sesion.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    
    return sesion, html_dashboard

# --- 3. FUNCIONES DE EXTRACCIÓN Y RESCATE MULTIFORMATO ---
def limpiar_nombre(nombre):
    return re.sub(r'[\\/*?:"<>|]', "", nombre).strip()

def descargar_archivo_real(sesion, url, carpeta, num_archivo, nombre_sugerido=None):
    url_directa = url + "&redirect=1" if "view.php" in url else url
        
    res = sesion.get(url_directa, verify=False, stream=True)
    content_type = res.headers.get('Content-Type', '').lower()
    
    if 'text/html' in content_type:
        soup_html = BeautifulSoup(res.text, 'html.parser')
        
        titulo = soup_html.find('h2').text if soup_html.find('h2') else (soup_html.title.text.replace("Curso:", "").strip() if soup_html.title else "Documento_Moodle")
        titulo_limpio = limpiar_nombre(titulo)
        
        enlace_archivo = None
        
        objeto_pdf = soup_html.find('object', type='application/pdf')
        if objeto_pdf and 'data' in objeto_pdf.attrs:
            enlace_archivo = objeto_pdf['data']
        else:
            for a in soup_html.find_all('a', href=True):
                href = a['href'].lower()
                if 'pluginfile.php' in href or any(href.endswith(ext) for ext in ['.pdf', '.xlsx', '.xls', '.docx', '.doc', '.pptx', '.zip']):
                    enlace_archivo = a['href']
                    break
        
        if enlace_archivo:
            print(f"¡Archivo rescatado de la web!: {titulo_limpio}")
            return descargar_archivo_real(sesion, urljoin(url, enlace_archivo), carpeta, num_archivo, titulo_limpio)
        else:
            print(f"Ignorado (Web externa sin archivo evidente): {url}")
            return "ignorados"

    nombre_base = nombre_sugerido if nombre_sugerido else f"apunte_{num_archivo}"
    extension_final = ""

    if "Content-Disposition" in res.headers:
        cd = res.headers["Content-Disposition"]
        if "filename=" in cd:
            nombre_real = cd.split("filename=")[1].strip('"\'').replace('"', '')
            _, ext = os.path.splitext(nombre_real)
            if ext:
                extension_final = ext.lower()
                if not nombre_sugerido:
                    nombre_base = nombre_real.replace(ext, "")
    
    if not extension_final:
        if 'spreadsheet' in content_type or 'excel' in content_type: extension_final = '.xlsx'
        elif 'word' in content_type: extension_final = '.docx'
        elif 'zip' in content_type: extension_final = '.zip'
        else: extension_final = '.pdf' 

    nombre_archivo = limpiar_nombre(nombre_base) + extension_final
    ruta_completa = os.path.join(carpeta, nombre_archivo)
    
    if os.path.exists(ruta_completa):
        print(f"Omitido (Ya existe): {nombre_archivo}")
        return "omitidos"
        
    with open(ruta_completa, 'wb') as f:
        for chunk in res.iter_content(chunk_size=8192):
            f.write(chunk)
            
    print(f"Descargado exitosamente: {nombre_archivo}")
    return "descargados"

# --- 4. EJECUCIÓN PRINCIPAL (VERSIÓN PILOTO AUTOMÁTICO CON REPORTES) ---
sesion_activa, html_dash = obtener_sesion_hibrida()

print("\nAnalizando tus cursos disponibles...")
soup_dash = BeautifulSoup(html_dash, 'html.parser')

cursos_dict = {}
for a in soup_dash.find_all('a', href=True):
    if 'course/view.php?id=' in a['href']:
        nombre = a.text.replace("Haga clic aquí para entrar al curso", "").strip()
        nombre = re.sub(r'\s+', ' ', nombre) 
        
        if len(nombre) > 5 and nombre not in cursos_dict.values():
            cursos_dict[a['href']] = nombre

if not cursos_dict:
    cursos_dict["https://www.ulagosvirtual.cl/course/view.php?id=4056"] = "Gestión Tributaria (Respaldo)"

MAPEO_RUTAS = {
    "Tributaria": r"C:\Users\lilo6\OneDrive\Escritorio\TRIBUTARIA 2026",
    "Finanzas": r"C:\Users\lilo6\OneDrive\Escritorio\FINANZAS AVANZADAS 2026",
    "Territorial": r"C:\Users\lilo6\OneDrive\Escritorio\TERRITORIAL 2026",
    "Proyectos": r"C:\Users\lilo6\OneDrive\Escritorio\PROYECTOS 2026"
}

print("\nIniciando Sincronización Automática de todos los módulos...")

estadisticas = {"descargados": 0, "omitidos": 0, "ignorados": 0}

def registrar_stat(resultado):
    if resultado in estadisticas:
        estadisticas[resultado] += 1

for url_curso, nombre_curso in cursos_dict.items():
    carpeta_destino = None
    
    for clave, ruta in MAPEO_RUTAS.items():
        if clave.lower() in nombre_curso.lower():
            carpeta_destino = ruta
            break
            
    if not carpeta_destino:
        print(f"Saltando curso (No mapeado en tu escritorio): {nombre_curso}")
        continue

    if not os.path.exists(carpeta_destino):
        os.makedirs(carpeta_destino)

    print(f"\n==================================================")
    print(f"Sincronizando: {nombre_curso}")
    print(f"Destino local: {carpeta_destino}")
    print(f"==================================================")

    response = sesion_activa.get(url_curso, verify=False)
    soup = BeautifulSoup(response.text, 'html.parser')
    enlaces_principales = soup.find_all('a', href=True)

    enlaces_directos = list(set([a['href'] for a in enlaces_principales if 'resource/view.php' in a['href'] or 'pluginfile.php' in a['href'] or 'url/view.php' in a['href']]))
    enlaces_carpetas = list(set([a['href'] for a in enlaces_principales if 'folder/view.php' in a['href']]))
    enlaces_secciones = list(set([a['href'] for a in enlaces_principales if 'course/section.php' in a['href']]))

    contador = 1
    
    for link in enlaces_directos:
        registrar_stat(descargar_archivo_real(sesion_activa, link, carpeta_destino, contador))
        contador += 1

    for carpeta_url in enlaces_carpetas:
        res_carpeta = sesion_activa.get(carpeta_url, verify=False)
        archivos_adentro = list(set([a['href'] for a in BeautifulSoup(res_carpeta.text, 'html.parser').find_all('a', href=True) if 'pluginfile.php' in a['href'] and 'forcedownload=1' in a['href']]))
        for link_interno in archivos_adentro:
            link_limpio = link_interno.split('?')[0] if '?' in link_interno and 'pluginfile' in link_interno else link_interno
            registrar_stat(descargar_archivo_real(sesion_activa, link_limpio, carpeta_destino, contador))
            contador += 1

    for seccion_url in enlaces_secciones:
        res_seccion = sesion_activa.get(seccion_url, verify=False)
        recursos_seccion = list(set([a['href'] for a in BeautifulSoup(res_seccion.text, 'html.parser').find_all('a', href=True) if 'resource/view.php' in a['href'] or 'pluginfile.php' in a['href'] or 'url/view.php' in a['href']]))
        for link in recursos_seccion:
            registrar_stat(descargar_archivo_real(sesion_activa, link, carpeta_destino, contador))
            contador += 1

ruta_reporte = r"C:\Users\lilo6\OneDrive\Escritorio\Reporte_Sincronizacion_Ulagos.txt"
fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

with open(ruta_reporte, "w", encoding="utf-8") as f:
    f.write("=========================================\n")
    f.write("  REPORTE EJECUTIVO DE SINCRONIZACIÓN\n")
    f.write("=========================================\n")
    f.write(f"Fecha de ejecución: {fecha_actual}\n\n")
    f.write("RESUMEN GLOBAL:\n")
    f.write(f"[+] Archivos NUEVOS descargados: {estadisticas['descargados']}\n")
    f.write(f"[-] Archivos OMITIDOS (ya existían): {estadisticas['omitidos']}\n")
    f.write(f"[!] Enlaces externos ignorados: {estadisticas['ignorados']}\n\n")
    f.write("ESTADO: Sistema al día y carpetas sincronizadas.\n")
    f.write("=========================================\n")

print(f"\n¡Sincronización Total Completada! Revisa el reporte en tu Escritorio.")
