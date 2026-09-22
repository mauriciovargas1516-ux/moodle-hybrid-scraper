import requests
from bs4 import BeautifulSoup
import os
import re
import tkinter as tk
from tkinter import filedialog
import urllib3
from urllib.parse import urljoin
import time

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
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
    
    driver = webdriver.Chrome(options=options)
    driver.get(URL_LOGIN)
    
    print("Por favor, inicia sesión manualmente en la ventana de Chrome.")
    print("Esperando acceso al Área Personal...")
    
    WebDriverWait(driver, 120).until(lambda d: "login" not in d.current_url.lower())
    
    print("¡Acceso concedido! Esperando que Moodle dibuje los cursos...")
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
    
    # 1. Si chocamos con una página web en lugar del archivo directo
    if 'text/html' in content_type:
        soup_html = BeautifulSoup(res.text, 'html.parser')
        
        titulo = soup_html.find('h2').text if soup_html.find('h2') else (soup_html.title.text.replace("Curso:", "").strip() if soup_html.title else "Documento_Moodle")
        titulo_limpio = limpiar_nombre(titulo)
        
        enlace_archivo = None
        
        # Primero buscamos visor PDF clásico
        objeto_pdf = soup_html.find('object', type='application/pdf')
        if objeto_pdf and 'data' in objeto_pdf.attrs:
            enlace_archivo = objeto_pdf['data']
        else:
            # Ahora buscamos cualquier enlace de descarga para Excel, Word, PPT, etc.
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
            return False

    # 2. PROCESAMIENTO DEL NOMBRE Y EXTENSIÓN REAL
    nombre_base = nombre_sugerido if nombre_sugerido else f"apunte_{num_archivo}"
    extension_final = ""

    # Extraemos la extensión real desde el servidor de la universidad
    if "Content-Disposition" in res.headers:
        cd = res.headers["Content-Disposition"]
        if "filename=" in cd:
            nombre_real = cd.split("filename=")[1].strip('"\'').replace('"', '')
            _, ext = os.path.splitext(nombre_real)
            if ext:
                extension_final = ext.lower()
                if not nombre_sugerido:
                    nombre_base = nombre_real.replace(ext, "")
    
    # Si el servidor no mandó la extensión, tratamos de adivinarla
    if not extension_final:
        if 'spreadsheet' in content_type or 'excel' in content_type: extension_final = '.xlsx'
        elif 'word' in content_type: extension_final = '.docx'
        elif 'zip' in content_type: extension_final = '.zip'
        else: extension_final = '.pdf' # Ante la duda total, asume PDF

    nombre_archivo = limpiar_nombre(nombre_base) + extension_final
    ruta_completa = os.path.join(carpeta, nombre_archivo)
    
    if os.path.exists(ruta_completa):
        print(f"Omitido (Ya existe): {nombre_archivo}")
        return True
        
    with open(ruta_completa, 'wb') as f:
        for chunk in res.iter_content(chunk_size=8192):
            f.write(chunk)
            
    print(f"Descargado exitosamente: {nombre_archivo}")
    return True

# --- 4. EJECUCIÓN PRINCIPAL ---
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

print("\n--- TUS MÓDULOS ---")
lista_urls = list(cursos_dict.keys())
for i, url_c in enumerate(lista_urls):
    print(f"[{i+1}] {cursos_dict[url_c]}")

try:
    opcion = int(input("\nIngresa el NÚMERO del módulo que deseas descargar: "))
    url_curso_elegido = lista_urls[opcion - 1]
except:
    print("Selección inválida. Saliendo.")
    exit()

root = tk.Tk()
root.withdraw()
print(f"\nSelecciona la carpeta donde guardar: {cursos_dict[url_curso_elegido]}")
carpeta_destino = filedialog.askdirectory(title=f"Guardando: {cursos_dict[url_curso_elegido]}")

if not carpeta_destino:
    print("Descarga cancelada.")
    exit()

print(f"\nExtrayendo archivos de {cursos_dict[url_curso_elegido]}...")
response = sesion_activa.get(url_curso_elegido, verify=False)
soup = BeautifulSoup(response.text, 'html.parser')

enlaces_principales = soup.find_all('a', href=True)
enlaces_directos = list(set([a['href'] for a in enlaces_principales if 'resource/view.php' in a['href'] or 'pluginfile.php' in a['href'] or 'url/view.php' in a['href']]))
enlaces_carpetas = list(set([a['href'] for a in enlaces_principales if 'folder/view.php' in a['href']]))

contador = 1
print(f"Rastreo principal: {len(enlaces_directos)} enlaces y {len(enlaces_carpetas)} carpetas encontradas.")

for link in enlaces_directos:
    descargar_archivo_real(sesion_activa, link, carpeta_destino, contador)
    contador += 1

for carpeta_url in enlaces_carpetas:
    res_carpeta = sesion_activa.get(carpeta_url, verify=False)
    archivos_adentro = list(set([a['href'] for a in BeautifulSoup(res_carpeta.text, 'html.parser').find_all('a', href=True) if 'pluginfile.php' in a['href'] and 'forcedownload=1' in a['href']]))
         
    for link_interno in archivos_adentro:
        link_limpio = link_interno.split('?')[0] if '?' in link_interno else link_interno
        descargar_archivo_real(sesion_activa, link_limpio, carpeta_destino, contador)
        contador += 1

print("\n¡Operación de rastreo y descarga masiva completada con éxito!")