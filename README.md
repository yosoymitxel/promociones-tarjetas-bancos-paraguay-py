# 🇵🇾 PromoScraper PY

> **Dashboard Consolidado de Beneficios, Alianzas y Descuentos Bancarios en Paraguay**

PromoScraper PY es una herramienta inteligente que recopila, analiza y unifica las promociones, descuentos, reintegros y cuotas sin intereses de las principales entidades bancarias y billeteras de Paraguay en un único dashboard interactivo.

🌐 **[Ver Dashboard en Vivo (GitHub Pages)](https://yosoymitxel.github.io/promociones-tarjetas-bancos-paraguay-py/)**
🔗 **[Repositorio en GitHub](https://github.com/yosoymitxel/promociones-tarjetas-bancos-paraguay-py)**

---

## ✨ Características Principales

*   **🔍 Búsqueda y Filtrado Avanzado:** Filtra promociones por banco, categoría, nivel de descuento (% OFF), días de la semana, cuotas sin interés y rangos de vigencia.
*   **📅 Extracción de Vigencia Automática:** Algoritmos de análisis de texto (Regex) extraen automáticamente las fechas de validez desde las descripciones de las promociones.
*   **🌓 Modo Claro / Oscuro (Dark Mode):** Interfaz premium tipo *glassmorphism* que se adapta a tus preferencias, con un botón de cambio rápido.
*   **📱 Modal de Detalles:** Visualiza rápidamente la imagen de la promoción, sus bases, condiciones y fechas de disponibilidad sin salir de la página.
*   **⚡ Generación Estática de Alto Rendimiento:** El frontend es un único archivo HTML (`index.html`) vitaminado con React y Tailwind CSS, ideal para hospedar de forma gratuita en GitHub Pages o cualquier servidor web.
*   **🛠️ Arquitectura de Scraping por Capas:** Diseñado con estrategias de "Fallback" en cascada para asegurar la obtención de datos:
    1.  **APIs Ocultas:** Interceptación de endpoints JSON (para máxima velocidad).
    2.  **HTML Parsing:** Extracción de sitios web estáticos (con BeautifulSoup).
    3.  **Playwright Automático:** Renderizado de Single Page Applications (SPAs) para sitios complejos y protección anti-bots.

---

## 🏦 Bancos y Entidades Soportadas

*   **Banco GNB** (Vía API)
*   **Banco Itaú Paraguay** (SPA - Vía Playwright)
*   **Banco BASA** (HTML Estático)
*   **Banco Continental** (SPA - Vía Playwright)
*   **Personal Pay** (Vía API)
*   **eClub** (Vía API)

*(Se filtran automáticamente registros duplicados basándose en un algoritmo determinístico MD5 para asegurar la correcta renderización en React).*

---

## 🚀 Guía de Instalación y Uso Local

### 1. Requisitos Previos

*   Python 3.10 o superior.
*   Navegadores de Playwright instalados (solo si planeas scrapear Itaú o Continental localmente).

### 2. Configuración del Entorno

Clona este repositorio e instala las dependencias:

```bash
git clone https://github.com/yosoymitxel/promociones-tarjetas-bancos-paraguay-py.git
cd promociones-tarjetas-bancos-paraguay-py

# Crear un entorno virtual (opcional pero recomendado)
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Instalar navegadores para Playwright (obligatorio para bancos complejos)
playwright install chromium
```

### 3. Ejecutar el Pipeline

Existen dos formas de ejecutar el scraper, dependiendo de la velocidad que requieras:

**A. Ejecución Completa (Recomendado para producción):**
Ejecutará todos los scrapers, incluyendo la inicialización de navegadores headless (Playwright) para sitios dinámicos. Esto tomará un par de minutos.
```bash
python main.py
```

**B. Ejecución Rápida (Solo APIs y HTML Estático):**
Ideal para pruebas rápidas o desarrollo del frontend. Omitirá los bancos que requieren Playwright (ej. Itaú, Continental).
```bash
python main.py --skip-playwright
```

### 4. Resultados

Al finalizar, el orquestador (`main.py`) generará:
1.  `promos.json`: La base de datos cruda consolidada.
2.  `index.html`: El dashboard inyectado con los datos listos para ser visualizado en tu navegador web.

Abre `index.html` en tu navegador favorito para disfrutar del dashboard.

---

## 🏗️ Estructura del Proyecto

```text
├── main.py                   # Orquestador principal (ejecuta todo el pipeline)
├── analysis.py               # Lógica de enriquecimiento de datos (Regex de descuentos, cuotas, fechas)
├── viewer_template.html      # Plantilla base (React + Tailwind) para el dashboard
├── requirements.txt          # Dependencias de Python
└── scraper_modules/
    ├── base.py               # Clase ScraperBase con lógica de deduplicación (MD5) y fallbacks
    └── scrapers.py           # Implementaciones individuales por entidad bancaria
```

---

## 🔍 SEO y Visibilidad

El archivo generado `index.html` cuenta con optimizaciones técnicas de primer nivel para motores de búsqueda:
*   Etiquetas Semánticas de HTML5.
*   Metaetiquetas dinámicas de **OpenGraph** (para compartir en redes sociales).
*   Estructura **JSON-LD Schema.org** (`WebApplication`), mejorando la indexación enriquecida en Google.

---

Desarrollado para la comunidad de Paraguay.
