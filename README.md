# Moodle Hybrid Scraper 

Un rastreador web de arquitectura híbrida diseñado para evadir barreras anti-bots, gestionar tokens de sesión dinámicos y automatizar la extracción masiva de documentos estructurados desde plataformas LMS (Moodle).

##  Características Técnicas

* Autenticación Híbrida (Session Hijacking):** Utiliza `Selenium` (Webdriver) para infiltrarse en formularios de login complejos protegidos por JavaScript, capturar el `logintoken` dinámico de Moodle y transferir las cookies autorizadas a un motor de alta velocidad.
*   **Extracción de Alta Velocidad:** Una vez superada la autenticación, abandona el navegador visual y utiliza `Requests` y `BeautifulSoup4` para ejecutar descargas masivas en segundos.
*   **Bypass de Visores Internos:** Algoritmo de parseo que desarma el código HTML para extraer rutas directas de archivos, saltándose los visores incrustados (`view.php`, `pluginfile.php`) y enlaces rotos.
*   **Detección Dinámica de Formatos:** Intercepta los encabezados HTTP (`Content-Disposition`) para identificar y renombrar al vuelo extensiones reales (.pdf, .xlsx, .docx, .zip) generadas por el servidor.
*   **CLI Interactivo:** Menú dinámico en consola para seleccionar los módulos a rastrear, integrado con `tkinter` para la gestión gráfica de directorios de salida.

## Stack Tecnológico

*   **Python 3.x**
*   `Requests` (Motor HTTP)
*   `Selenium` (Automatización de navegador / Evasión JS)
*   `BeautifulSoup4` (Parseo del DOM)
*   `Tkinter` (GUI de sistema de archivos)

## Aviso de Uso
Este proyecto fue desarrollado con fines estrictamente educativos y como prueba de concepto (PoC) sobre automatización y web scraping en arquitecturas cerradas. El uso de herramientas de extracción automatizada en plataformas de producción sin autorización puede violar los Términos de Servicio de la institución.
