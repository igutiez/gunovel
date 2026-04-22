# Especificación técnica: Aplicación de escritura de novelas asistida por IA

*Documento de referencia para la implementación. Versión 1.0.*

---

## 0. Propósito del documento

Este documento describe una aplicación web para escritura de novelas en la que una IA (Claude vía API de Anthropic) actúa como ejecutora principal: redacta prosa, mantiene documentación del proyecto, propaga cambios canónicos y detecta incoherencias, mientras que el usuario ejerce la dirección narrativa, toma las decisiones y corrige puntualmente.

El documento es la especificación de referencia para implementar la aplicación. Debe leerse completo antes de escribir código. Las decisiones tomadas aquí son deliberadas y fruto de un diseño iterativo; desviarse de ellas sin razón técnica concreta introduce complejidad innecesaria.

La implementación se desplegará en un servidor privado ya provisto por el operador. La configuración de HTTPS, protección de red, dominio y tunelización es responsabilidad externa a la aplicación y no forma parte de este documento.

---

## 1. Filosofía y principios rectores

La aplicación existe para resolver un flujo de trabajo concreto: el novelista dicta dirección narrativa, la IA ejecuta el trabajo de escritura y mantenimiento documental, el sistema garantiza que nada se pierde y que el canon narrativo permanece coherente.

Los principios que rigen toda decisión de diseño son ocho. Deben respetarse siempre.

**Principio 1 — Una entidad, un fichero.** Cada pieza narrativa (un capítulo, un personaje, un lugar) tiene exactamente un fichero en disco. Las versiones anteriores viven en Git, nunca como ficheros paralelos. No existen `cap03_v2.md`, `cap03_final.md`, `cap03_backup.md`.

**Principio 2 — Nombre estable; título y posición son capas separadas.** El nombre del fichero (`jose_luis.md`) es un identificador estable y descriptivo que no cambia durante la vida del proyecto. El título humano del capítulo vive dentro del fichero. La posición en la secuencia narrativa vive en un fichero índice separado.

**Principio 3 — Numeración externa.** Los ficheros no contienen su número de capítulo. La etiqueta "Capítulo 3" se calcula desde el orden y se aplica solo en presentación (UI y exportación).

**Principio 4 — Los capítulos son prosa pura.** Los ficheros de capítulo contienen únicamente cabecera YAML mínima y prosa publicable. No hay notas embebidas, no hay metacomentarios, no hay marcadores de sección fuera de los propios encabezados narrativos.

**Principio 5 — Fuente única de verdad.** Cada hecho narrativo (rasgo de personaje, propiedad de un lugar, elemento de continuidad, decisión editorial) vive en exactamente un fichero. Los demás ficheros referencian ese hecho, nunca lo duplican.

**Principio 6 — La IA propaga y respeta el canon.** Al modificar un fichero, la IA evalúa qué otros ficheros pueden necesitar actualización coordinada y propone esos cambios antes de aplicar nada. Al escribir prosa, consulta el canon antes de inventar detalles y, si inventa, lo registra en la ficha correspondiente.

**Principio 7 — Multi-proyecto con canon compartido para sagas.** Un proyecto es una novela independiente o un conjunto de libros que comparten canon (saga). El canon compartido vive en un espacio común accesible desde todos los libros de la saga.

**Principio 8 — Acceso protegido por login.** La aplicación requiere autenticación para cualquier acceso. Un único usuario autor se autentica con credenciales almacenadas como hash.

---

## 2. Arquitectura general

### 2.1 Stack tecnológico

- **Backend:** Python 3.11+ con Flask.
- **Frontend:** HTML + CSS + JavaScript. Sin framework pesado. Opcionalmente Alpine.js o HTMX para interactividad ligera.
- **Base de datos:** SQLite para audit trail y metadatos de aplicación.
- **Almacenamiento de contenido:** sistema de ficheros con estructura de carpetas por proyecto.
- **Control de versiones:** Git vía `subprocess` (llamadas al binario `git`).
- **IA:** SDK oficial `anthropic` de Python contra la API de Anthropic.
- **Autenticación:** Flask-Login con hashes generados por `werkzeug.security`.
- **Editor Markdown en frontend:** CodeMirror 6 o EasyMDE.
- **Renderizado Markdown:** `markdown` (Python) para server-side, `marked.js` para client-side si hace falta preview en vivo.
- **Servidor WSGI:** Gunicorn (el despliegue lo gestiona el operador).

### 2.2 Componentes principales

La aplicación se organiza en cinco componentes lógicos:

1. **Capa de autenticación.** Login, sesiones, decoradores de protección de rutas.
2. **Capa de ficheros.** CRUD sobre la estructura de carpetas de proyectos. Parsing de cabeceras YAML. Gestión del fichero `orden.json`.
3. **Capa de IA.** Bucle de tool use controlado, ensamblado de contexto, caché de bloques estables, interpretación de respuestas con propuestas de cambio.
4. **Capa de versionado.** Operaciones Git (init, commit, push, log, restore) para cada proyecto.
5. **Capa de audit.** Registro de eventos, consultas, asociación con commits Git.

### 2.3 Estructura del repositorio de código

```
novela-app/
├── app/
│   ├── __init__.py
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── models.py
│   ├── files/
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   ├── parser.py
│   │   └── project.py
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   ├── tool_use.py
│   │   ├── context_builder.py
│   │   ├── prompts.py
│   │   └── cache.py
│   ├── versioning/
│   │   ├── __init__.py
│   │   ├── git_ops.py
│   │   └── routes.py
│   ├── audit/
│   │   ├── __init__.py
│   │   ├── db.py
│   │   └── routes.py
│   └── main/
│       ├── __init__.py
│       └── routes.py
├── static/
│   ├── css/
│   ├── js/
│   └── img/
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── app.html
│   └── partials/
├── config/
│   ├── config.example.yaml
│   └── users.example.json
├── manage.py
├── wsgi.py
├── requirements.txt
├── .env.example
└── README.md
```

---

## 3. Modelo de datos en disco

### 3.1 Directorio raíz de proyectos

La aplicación opera sobre un directorio raíz configurable (vía variable de entorno `NOVELAS_ROOT`, por defecto `/var/novelas/`). Bajo ese directorio se organizan los proyectos en dos categorías:

```
$NOVELAS_ROOT/
├── independientes/
│   └── <slug_novela>/
│       └── (estructura de novela)
│
└── sagas/
    └── <slug_saga>/
        ├── 00_canon_compartido/
        │   └── (estructura de canon)
        ├── libro_<N>_<slug_libro>/
        │   └── (estructura de novela, sin canon compartido)
        └── .saga-config.json
```

### 3.2 Estructura de una novela independiente

```
<slug_novela>/
├── 00_concepto/
│   ├── premisa.md
│   ├── sinopsis.md
│   └── tesis.md
├── 01_personajes/
│   ├── <slug_personaje_1>.md
│   ├── <slug_personaje_2>.md
│   └── ...
├── 02_mundo/
│   ├── <slug_lugar_1>.md
│   ├── <slug_lugar_2>.md
│   ├── worldbuilding.md
│   ├── glosario.md
│   └── mapa.md (opcional)
├── 03_estructura/
│   ├── actos.md
│   ├── escaleta.md
│   ├── cronologia.md
│   ├── pov.md
│   ├── relaciones.md
│   └── orden.json
├── 04_capitulos/
│   ├── <slug_capitulo_1>.md
│   ├── <slug_capitulo_2>.md
│   └── ...
├── 05_control/
│   ├── estilo.md
│   ├── raccord.md
│   └── bitacora.md
├── 06_revision/
│   ├── plan_correcciones.md
│   └── notas_editoriales.md
├── 07_investigacion/
│   ├── fuentes.md
│   └── referencias/
├── .novela-config.json
├── .gitignore
└── .git/ (tras inicialización)
```

### 3.3 Estructura del canon compartido en sagas

```
00_canon_compartido/
├── personajes/
│   └── <slug_personaje>.md
├── mundo/
│   └── <slug_lugar>.md
├── cronologia_saga.md
├── reglas_universo.md
├── estilo.md
└── bitacora_saga.md
```

Los libros dentro de una saga replican la estructura de novela independiente pero **sin** los ficheros que ya están en el canon compartido. Específicamente, no tienen carpetas `01_personajes/` ni `02_mundo/` propias si todos los personajes y lugares son compartidos. Si un libro tiene personajes o lugares exclusivos, sí mantiene esas carpetas para ellos.

### 3.4 Convención de nombres de ficheros

Los slugs siguen estas reglas:

- Solo caracteres ASCII minúsculos, dígitos y guiones bajos.
- Sin espacios, sin tildes, sin eñes, sin mayúsculas.
- Descriptivos, identificativos de la entidad.
- Estables: una vez asignados no cambian durante la vida del proyecto.
- Extensión `.md` para todos los ficheros de contenido.

Ejemplos: `jose_luis.md`, `faro_castro.md`, `primera_noche.md`, `el_hallazgo.md`.

Contraejemplos: `Capitulo 3.md`, `josé_luis.md`, `cap03.md`, `personaje_principal.md`.

### 3.5 Estructura interna de un fichero de capítulo

```markdown
---
slug: jose_luis
personajes: [oli, jose_luis]
pov: oli
estado: borrador_v2
---

# José Luis

[prosa pura, sin notas, sin metacomentarios]
```

**Cabecera YAML (obligatoria):**
- `slug` (string): identificador del capítulo, idéntico al nombre del fichero sin extensión.
- `personajes` (lista de strings): slugs de personajes presentes en el capítulo.
- `pov` (string): slug del personaje cuyo punto de vista narra.
- `estado` (string enum): `esqueleto | borrador | borrador_v2 | revisado | cerrado`.

**Cuerpo:** prosa pura en Markdown. El primer encabezado `# ...` es el título del capítulo para la UI y la exportación.

### 3.6 Estructura interna de una ficha de personaje

```markdown
---
slug: jose_luis
tipo: personaje
aparece_en: [jose_luis, el_hallazgo, la_confrontacion]
rol: secundario
---

# José Luis

## Identidad
- Edad: 52
- Profesión: antiguo farero.

## Rasgos físicos permanentes
- Cazadora verde oliva, desgastada en los codos.
- Cojera leve en pierna izquierda.

## Arco
- Introducido en [jose_luis](../04_capitulos/jose_luis.md).
- Confrontación final en [la_confrontacion](../04_capitulos/la_confrontacion.md).

## Conocimiento
- Desde siempre: secreto del faro.
- Aprende en jose_luis: que Oli investiga.

## Voz
- Frases cortas.
- Evita nombres propios.
- Tic verbal: "bueno, bueno".
```

**Campos YAML obligatorios:**
- `slug`, `tipo` (siempre `personaje`), `aparece_en` (lista de slugs de capítulos), `rol` (`principal | secundario | terciario | mencionado`).

### 3.7 Estructura interna de una ficha de lugar

```markdown
---
slug: faro_castro
tipo: lugar
aparece_en: [jose_luis, el_hallazgo, la_confrontacion]
---

# Faro de Castro

## Descripción física
- Torre blanca de 24 metros.
- Construcción de 1853, restaurada en 1972.
- Acceso por rampa de San Guillén.

## Historia
- Abandonado desde 1998.
- Antiguo farero: José Luis.

## Relevancia narrativa
- Escenario del hallazgo.
- Símbolo del secreto oculto del pueblo.
```

### 3.8 Estructura del fichero `orden.json`

```json
{
  "capitulos": [
    {"slug": "llegada_castro"},
    {"slug": "primera_noche"},
    {"slug": "jose_luis"},
    {"slug": "el_hallazgo"},
    {"slug": "la_confrontacion"}
  ],
  "prologo": {"slug": "prologo", "etiqueta": "Prólogo"},
  "epilogo": {"slug": "epilogo", "etiqueta": "Epílogo"}
}
```

**Campos:**
- `capitulos` (lista obligatoria): orden canónico de los capítulos numerables.
- `prologo` (opcional): capítulo con etiqueta especial antes de la numeración.
- `epilogo` (opcional): capítulo con etiqueta especial después de la numeración.

Los capítulos con etiqueta propia no cuentan para la numeración. En el ejemplo, `llegada_castro` es "Capítulo 1", `primera_noche` es "Capítulo 2", etc.

### 3.9 Estructura del fichero `relaciones.md`

Fichero Markdown con secciones que mapean el grafo de dependencias narrativas. No es una estructura de datos estricta pero sigue un formato predecible:

```markdown
# Grafo de relaciones

## Por capítulo

### jose_luis
- Personajes presentes: [oli](../01_personajes/oli.md), [jose_luis](../01_personajes/jose_luis.md)
- Escenarios: [faro_castro](../02_mundo/faro_castro.md)
- Depende de: llegada_castro, primera_noche
- Referenciado por: el_hallazgo, la_confrontacion
- Introduce: personaje jose_luis, tema del secreto del faro

### el_hallazgo
- ...

## Por personaje

### jose_luis
- Aparece en: jose_luis, el_hallazgo, la_confrontacion
- Mencionado en: primera_noche (sin nombre)
```

Este fichero es mantenido principalmente por la IA con herramienta específica (ver sección 6.3).

### 3.10 Configuración de proyecto (`.novela-config.json`)

```json
{
  "tipo": "novela",
  "nombre": "Chari",
  "slug": "chari",
  "creado": "2026-04-21T10:00:00Z",
  "modelo_por_defecto": "claude-sonnet-4-6",
  "modelo_para_revision_editorial": "claude-opus-4-7",
  "estilo_resumen": "comedia costumbrista, tono cálido",
  "idioma": "es",
  "git": {
    "remoto_url": "git@github.com:usuario/chari-novela.git",
    "auto_push": true
  }
}
```

Para sagas, el fichero equivalente es `.saga-config.json`:

```json
{
  "tipo": "saga",
  "nombre": "Alianza",
  "slug": "alianza",
  "libros": [
    {"slug": "libro_1_senales", "titulo": "Señales", "orden": 1},
    {"slug": "libro_2_guerra", "titulo": "Guerra", "orden": 2},
    {"slug": "libro_3_rebelion", "titulo": "Rebelión", "orden": 3}
  ],
  "modelo_por_defecto": "claude-sonnet-4-6",
  "git": {
    "remoto_url": "git@github.com:usuario/alianza-saga.git",
    "auto_push": true
  }
}
```

Y cada libro dentro de la saga tiene su `.libro-config.json`:

```json
{
  "tipo": "libro",
  "nombre": "Guerra",
  "slug": "libro_2_guerra",
  "numero_en_saga": 2,
  "estado": "borrador_v3"
}
```

---

## 4. Autenticación y sesión

### 4.1 Modelo de usuario

Un único usuario por instalación. Almacenado en fichero JSON fuera del repositorio de contenido:

**Ruta:** `$APP_CONFIG_DIR/users.json` (por defecto `/var/lib/novela-app/users.json`).

**Formato:**

```json
{
  "username": "inigo",
  "password_hash": "pbkdf2:sha256:600000$xyzabc...",
  "created_at": "2026-04-21T10:00:00Z",
  "last_login": "2026-04-21T15:30:00Z"
}
```

**Permisos:** el fichero debe tener permisos `600` (solo lectura/escritura del propietario).

### 4.2 Gestión de contraseñas

- **Hashing:** `werkzeug.security.generate_password_hash(password)`.
- **Verificación:** `werkzeug.security.check_password_hash(stored_hash, provided_password)`.
- **Algoritmo por defecto:** PBKDF2-SHA256 con 600.000 iteraciones.

La contraseña en texto plano **nunca** se almacena, loguea, ni se envía por ningún canal.

### 4.3 Script CLI de gestión de usuario

En `manage.py`:

```python
# Uso: python manage.py set_password
# Pregunta la contraseña por stdin sin eco (usar getpass.getpass()).
# Hashea y sobrescribe el fichero users.json.
# Comando: python manage.py set_password
```

### 4.4 Login

**Endpoint:** `POST /login`.

**Flujo:**
1. Recibe `username` y `password` del formulario.
2. Lee `users.json`. Si el `username` no coincide con el único usuario configurado, error genérico.
3. Verifica el hash. Si falla, error genérico ("Credenciales inválidas").
4. Si es correcto, establece sesión Flask-Login con el usuario.
5. Actualiza `last_login` en `users.json`.
6. Redirige a la página principal `/`.

**Error genérico:** nunca distinguir en el mensaje si falló el usuario o la contraseña.

### 4.5 Protección de rutas

- Todas las rutas de la aplicación (excepto `/login`, `/logout` y assets estáticos) requieren `@login_required`.
- Si un usuario no autenticado accede a cualquier ruta protegida, redirige a `/login`.

### 4.6 Sesión

- **Biblioteca:** Flask-Login.
- **Cookie:** `HttpOnly`, `SameSite=Strict`, `Secure=True` (asumiendo HTTPS por infraestructura externa).
- **Duración:** 8 horas de inactividad. Renovación sliding (cada petición refresca el timeout).
- **Clave secreta de sesión:** variable de entorno `SECRET_KEY`. Generar con `secrets.token_hex(32)` la primera vez y guardarla en `.env`.

### 4.7 Logout

**Endpoint:** `POST /logout`.
Destruye la sesión actual y redirige a `/login`.

### 4.8 Log de accesos

Fichero de texto en `$APP_CONFIG_DIR/logs/access.log`, rotación semanal.

**Formato:**
```
[2026-04-21 14:32:15] LOGIN_OK inigo desde 82.45.123.45
[2026-04-21 14:35:02] LOGIN_FAIL unknown desde 185.22.11.88
[2026-04-21 16:12:44] LOGOUT inigo
```

Usar el módulo `logging` de Python con `RotatingFileHandler` o `TimedRotatingFileHandler`.

### 4.9 Proxy reverso

La aplicación espera correr detrás de un proxy (Cloudflare Tunnel, nginx, etc.). Aplicar `ProxyFix`:

```python
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
```

Esto asegura que las IPs registradas y las cookies se comporten correctamente.

---

## 5. Capa de ficheros

### 5.1 Responsabilidades

La capa de ficheros gestiona todas las operaciones sobre el sistema de ficheros:

- Listar proyectos disponibles.
- Cargar la estructura de árbol de un proyecto.
- Leer, crear, modificar ficheros de contenido.
- Parsear cabeceras YAML y extraer metadatos.
- Leer y escribir `orden.json`.
- Calcular numeración de capítulos a partir de `orden.json`.
- Validar integridad estructural (p. ej., slugs coinciden con nombres de fichero).

### 5.2 Operaciones sobre ficheros

Todas las operaciones de escritura deben:

1. Validar que la ruta está dentro del proyecto activo (prevención de path traversal).
2. Escribir atómicamente (escribir a fichero temporal, luego renombrar).
3. Disparar commit Git tras la escritura exitosa.
4. Registrar evento en audit trail.

### 5.3 Parser de Markdown con cabecera YAML

Librería: `python-frontmatter` o implementación simple manual.

**API interna:**

```python
def parse_fichero(ruta: Path) -> dict:
    """
    Retorna:
    {
        "metadata": {...},  # cabecera YAML parseada
        "content": "...",   # cuerpo Markdown
        "title": "...",     # primer # encontrado en el cuerpo
    }
    """
```

### 5.4 Cálculo de numeración

Dada la lectura de `orden.json`, para cada capítulo se calcula:

```python
def numerar_capitulos(orden: dict) -> dict:
    """
    Input: contenido parseado de orden.json
    Output: dict {slug: etiqueta_para_ui}
    Ejemplo:
    {
        "prologo": "Prólogo",
        "llegada_castro": "Capítulo 1",
        "primera_noche": "Capítulo 2",
        "jose_luis": "Capítulo 3",
        "epilogo": "Epílogo"
    }
    """
```

### 5.5 Endpoints principales

**`GET /api/proyectos`**
Lista todos los proyectos disponibles (independientes + sagas con sus libros).

Response:
```json
{
  "independientes": [
    {"slug": "chari", "nombre": "Chari", "ruta": "independientes/chari"},
    {"slug": "norte", "nombre": "NORTE", "ruta": "independientes/norte"}
  ],
  "sagas": [
    {
      "slug": "alianza",
      "nombre": "Alianza",
      "libros": [
        {"slug": "libro_1_senales", "titulo": "Señales", "orden": 1},
        {"slug": "libro_2_guerra", "titulo": "Guerra", "orden": 2}
      ]
    }
  ]
}
```

**`GET /api/proyecto/<slug>/arbol`**
Devuelve la estructura de carpetas y ficheros del proyecto activo.

Response:
```json
{
  "carpetas": [
    {
      "nombre": "04_capitulos",
      "titulo_humano": "Capítulos",
      "ficheros": [
        {
          "slug": "llegada_castro",
          "ruta": "04_capitulos/llegada_castro.md",
          "titulo": "Llegada a Castro",
          "etiqueta_ui": "Capítulo 1",
          "tipo": "capitulo",
          "metadata": {"estado": "borrador_v2", "personajes": ["oli", "esti"]}
        }
      ]
    }
  ]
}
```

**`GET /api/proyecto/<slug>/fichero?ruta=<ruta_relativa>`**
Lee el contenido de un fichero.

Response:
```json
{
  "ruta": "04_capitulos/jose_luis.md",
  "metadata": {"slug": "jose_luis", "personajes": ["oli", "jose_luis"], "pov": "oli"},
  "title": "José Luis",
  "content": "...",
  "last_modified": "2026-04-21T14:32:15Z",
  "last_commit": "a3f2c19"
}
```

**`PUT /api/proyecto/<slug>/fichero`**
Modifica un fichero existente.

Request:
```json
{
  "ruta": "04_capitulos/jose_luis.md",
  "content": "...",
  "commit_message": "Edición manual de diálogo"
}
```

Response: confirmación con hash del nuevo commit.

**`POST /api/proyecto/<slug>/fichero`**
Crea un fichero nuevo. Falla si ya existe.

**`POST /api/proyecto/<slug>/reordenar`**
Modifica el orden de capítulos. Actualiza `orden.json`.

Request:
```json
{
  "nuevo_orden": ["llegada_castro", "jose_luis", "primera_noche", "el_hallazgo"]
}
```

---

## 6. Capa de IA

### 6.1 Responsabilidades

- Recibir mensajes del usuario en el chat.
- Ensamblar el contexto apropiado según la tarea y el fichero activo.
- Mantener la conversación en la sesión (historial).
- Ejecutar el bucle de tool use controlado.
- Aplicar caché agresiva en bloques estables.
- Interpretar las propuestas de cambio de la IA y preparar diffs para aprobación del usuario.
- Registrar costes por llamada.

### 6.2 Herramientas disponibles para la IA

La IA dispone **exclusivamente** de las herramientas definidas a continuación. No hay Bash, WebFetch, WebSearch, ni ejecución de código.

**`leer_fichero(ruta: str) -> dict`**
Lee un fichero del proyecto activo. Retorna metadata, título y contenido.

**`modificar_fichero(ruta: str, contenido_nuevo: str, motivo: str) -> dict`**
Modifica un fichero existente. Requiere `motivo` (una frase explicando el cambio). No ejecuta la modificación directamente: deja la propuesta en cola para aprobación del usuario.

**`crear_fichero(ruta: str, contenido: str, motivo: str) -> dict`**
Crea un fichero nuevo. Falla si la ruta ya existe. Requiere motivo. Igualmente en cola para aprobación.

**`listar_ficheros_proyecto(subcarpeta: str = None) -> list`**
Lista ficheros del proyecto, opcionalmente filtrando por subcarpeta.

**`buscar_texto(query: str, subcarpeta: str = None) -> list`**
Grep acotado al proyecto activo. Retorna lista de `{ruta, linea, contexto}`.

**`consultar_grafo_relaciones(entidad: str = None) -> dict`**
Lee `03_estructura/relaciones.md` parseado. Si se pasa `entidad`, devuelve solo las relaciones que la involucran.

**`actualizar_grafo_relaciones(cambios: list, motivo: str) -> dict`**
Propone modificaciones al grafo. Igualmente en cola para aprobación.

**`obtener_info_capitulo(slug: str) -> dict`**
Retorna: `{slug, titulo, posicion, etiqueta_ui, anterior, siguiente, personajes, pov}`.

**`reordenar_capitulos(nuevo_orden: list, motivo: str) -> dict`**
Propone un nuevo orden. En cola para aprobación.

**`verificar_coherencia(ambito: str) -> dict`**
Ejecuta una verificación de coherencia sobre un ámbito (un capítulo, un personaje, todo el proyecto). Retorna lista de posibles incoherencias detectadas. Solo lectura, no modifica nada.

### 6.3 Bucle de tool use

Implementación sobre la API de Anthropic con la capacidad `tools`. Flujo:

1. Usuario envía mensaje en el chat.
2. App ensambla contexto (ver 6.4).
3. App llama a la API con `messages` + `tools` + `tool_choice: auto`.
4. Si la respuesta contiene tool calls:
   - Para herramientas de **solo lectura** (leer_fichero, buscar_texto, consultar_grafo, listar_ficheros, obtener_info_capitulo, verificar_coherencia): ejecutar inmediatamente y añadir resultado al historial.
   - Para herramientas de **escritura** (modificar_fichero, crear_fichero, actualizar_grafo, reordenar_capitulos): **no** ejecutar directamente. Acumular la propuesta en una cola asociada a esta interacción.
5. Si la respuesta final contiene propuestas de escritura pendientes, presentarlas al usuario agrupadas con diff.
6. Usuario aprueba/rechaza cada propuesta individualmente o en bloque.
7. Solo tras aprobación, la operación de escritura se ejecuta (commit Git + audit).

### 6.4 Límite de iteraciones

**Máximo 5 tool calls por turno del usuario.** Si la IA intenta una sexta, el bucle se corta y se añade al historial un mensaje del sistema:

> "Has alcanzado el límite de 5 herramientas en esta interacción. Resume tu progreso y pregunta al usuario si debes continuar."

Esto previene bucles exploratorios como los de Claude Code.

### 6.5 Ensamblado de contexto

El ensamblado de contexto ocurre al principio de cada turno, en tres capas con caché diferenciada:

**Capa 1 — Estable (cacheada agresivamente):**
- Premisa, tesis, sinopsis.
- Estilo.
- Lista compacta de personajes principales (una línea cada uno).
- Estructura de actos.
- Si es saga: canon compartido relevante.

Esta capa se marca con `cache_control: {"type": "ephemeral"}` y TTL de 1 hora (multiplicador 2x en primera escritura, 0.1x en lecturas posteriores).

**Capa 2 — Semi-estable (cacheada):**
- Si el fichero activo es un capítulo: escaleta completa, raccord, entrada correspondiente de relaciones.md.
- Si es una ficha: relaciones que la involucran.

TTL de 5 minutos (multiplicador 1.25x / 0.1x).

**Capa 3 — Variable (sin caché):**
- Fichero activo actual.
- Capítulo anterior (si aplica).
- Fichas completas de personajes presentes (si es un capítulo).
- Instrucción del usuario.

### 6.6 System prompt

Template base (adaptable por proyecto según configuración):

```
Eres el colaborador editorial y redactor de una novela. Tu rol es:
- Redactar prosa de capítulos siguiendo la escaleta, el estilo definido y el canon establecido.
- Mantener actualizada la documentación del proyecto (biblia de personajes, raccord, grafo de relaciones) cuando los cambios lo requieran.
- Detectar incoherencias con el canon establecido.
- Proponer cambios siempre con motivo explícito y breve.

Principios de trabajo:
- No inventes rasgos de personajes, lugares ni hechos de continuidad sin consultar antes las fichas correspondientes. Si necesitas un detalle no documentado, proponlo primero como añadido a la ficha y luego úsalo en la prosa.
- Al modificar un capítulo, evalúa si los cambios afectan al raccord, al grafo de relaciones, a fichas de personajes o a la escaleta. Si es así, propón esas actualizaciones como parte de la misma operación.
- No uses referencias numéricas a capítulos en la prosa narrativa ("como vimos en el capítulo 3"). Usa referencias narrativas ("la noche en el faro", "cuando Oli conoció a José Luis").
- Cada propuesta de escritura debe ir con un motivo breve (una frase).

Estilo del proyecto:
<contenido de 05_control/estilo.md>

Personajes principales:
<resumen de personajes desde 01_personajes/>

Estructura general:
<contenido de 03_estructura/actos.md>
```

### 6.7 Modelos y coste

**Modelo por defecto:** `claude-sonnet-4-6` para la mayoría de tareas.

**Modelo Opus** (`claude-opus-4-7`): reservado para:
- Revisiones editoriales completas del libro.
- Establecimiento inicial de biblia de personajes.
- Reescrituras de capítulos pivote (clímax, detonantes, resolución).

El modelo es configurable por proyecto en `.novela-config.json` y puede sobrescribirse por llamada si el usuario lo solicita explícitamente.

**Registro de coste por llamada:**
Cada llamada a la API registra en audit trail:
- Tokens input normales.
- Tokens input cacheados (leídos de caché).
- Tokens input para escritura de caché.
- Tokens output.
- Coste calculado en euros (convertir de USD con tasa fija configurable, por defecto 0.92).

### 6.8 Gestión de sesiones de chat

- Una sesión de chat por proyecto activo.
- Historial de mensajes persistido en SQLite (ver sección 9).
- El historial se incluye en las llamadas a la API hasta un límite de ventana configurable (por defecto 50 mensajes o 100k tokens, lo que ocurra antes).
- Al superar el límite, los mensajes más antiguos se resumen y se sustituyen por un resumen sintético.

### 6.9 Diff y aprobación de cambios

Cuando la IA produce propuestas de escritura:

1. La respuesta del chat incluye un bloque con las propuestas pendientes.
2. Por cada propuesta, se genera un diff entre el contenido actual del fichero y el propuesto.
3. El diff se muestra en formato unified (rojo/verde) en el panel central.
4. Opciones por propuesta: **Aplicar**, **Rechazar**, **Editar antes de aplicar**.
5. Si hay múltiples propuestas relacionadas (p. ej., modificar capítulo + actualizar raccord), hay también botones **Aplicar todas**, **Rechazar todas**.
6. Tras la decisión:
   - Aplicar: escribe fichero → commit Git → push → registro en audit.
   - Rechazar: registro en audit (`tipo: diff_rechazado`).
   - Editar: abrir el contenido propuesto en editor para ajustes, luego aplicar.

---

## 7. Capa de versionado

### 7.1 Inicialización de repositorio

Al crear un proyecto nuevo:

1. Crear estructura de carpetas.
2. Crear ficheros base (premisa, estilo, etc.) con plantillas.
3. Crear `.gitignore`:
   ```
   .DS_Store
   Thumbs.db
   *.tmp
   ```
4. Ejecutar `git init`.
5. Configurar `user.name` y `user.email` localmente en el repo (desde `.novela-config.json`):
   ```
   git config user.name "Inigo Gutiez"
   git config user.email "inigo@ejemplo.com"
   ```
6. Primer commit: `git add . && git commit -m "[SYS] Inicialización del proyecto"`.
7. Si hay `remoto_url` configurado: `git remote add origin <url>` y primer push.

### 7.2 Commits tras modificaciones

Cada escritura (manual o por IA) produce un commit con mensaje estructurado:

**Por la IA:**
```
[IA] <ruta>: <motivo>

Conversación: <conv_id>
Tokens: <input>/<output> (cached: <cached>)
Coste: <euros>€
Modelo: <modelo>
```

**Por el usuario:**
```
[YO] <ruta>: <mensaje_usuario o "Edición manual">
```

**Por el sistema:**
```
[SYS] <descripción>
```

### 7.3 Push automático

Tras cada commit, si `auto_push: true` en config:
- Ejecutar `git push origin main` en background (thread separado o cola).
- Si falla, registrar en log de sistema, marcar estado del repo como "pendiente_sincronizar".
- No bloquear al usuario por un push fallido.

### 7.4 Indicador de estado de sincronización

Endpoint `GET /api/proyecto/<slug>/git_status`:

Response:
```json
{
  "estado": "sincronizado|pendiente|error",
  "commits_pendientes": 0,
  "ultimo_push": "2026-04-21T14:32:00Z",
  "ultimo_commit": "a3f2c19",
  "remoto_url": "git@github.com:...",
  "error_ultimo": null
}
```

La UI renderiza un pequeño indicador visual:
- Verde: `sincronizado`, 0 pendientes.
- Amarillo: `pendiente`, N pendientes.
- Rojo: `error`, con tooltip del error.

### 7.5 Historial por fichero

Endpoint `GET /api/proyecto/<slug>/fichero/historial?ruta=<ruta>`:

Response:
```json
{
  "ruta": "04_capitulos/jose_luis.md",
  "versiones": [
    {
      "commit": "a3f2c19",
      "fecha": "2026-04-21T14:32:15Z",
      "autor": "IA",
      "motivo": "Reescritura arco Sara → externo",
      "tokens": {"input": 8420, "output": 3200, "cached": 6100},
      "coste_eur": 0.041
    },
    {
      "commit": "b2e3d4a",
      "fecha": "2026-04-18T09:15:00Z",
      "autor": "YO",
      "motivo": "Edición manual - pulido de diálogo"
    }
  ]
}
```

Implementación: `git log --pretty=format:... <ruta>` parseando el output.

### 7.6 Ver versión concreta

Endpoint `GET /api/proyecto/<slug>/fichero/version?ruta=<ruta>&commit=<hash>`:
Retorna el contenido del fichero en el commit especificado. Implementación: `git show <hash>:<ruta>`.

### 7.7 Restaurar versión

Endpoint `POST /api/proyecto/<slug>/fichero/restaurar`:

Request:
```json
{
  "ruta": "04_capitulos/jose_luis.md",
  "commit": "b2e3d4a"
}
```

Flujo:
1. Obtener contenido: `git show <commit>:<ruta>`.
2. Escribir como versión actual.
3. Commit con mensaje `[SYS] Restaurado <ruta> a versión de <fecha>`.
4. Push automático.
5. Registrar en audit.

### 7.8 Deshacer último cambio

Endpoint `POST /api/proyecto/<slug>/deshacer`:
Revierte el último commit del usuario actual. Implementación: `git revert HEAD --no-edit`.

---

## 8. Capa de audit

### 8.1 Esquema SQLite

Base de datos: `$APP_CONFIG_DIR/audit.db`. Una sola base para toda la aplicación, con un campo que identifica el proyecto.

**Tabla `eventos`:**
```sql
CREATE TABLE eventos (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    proyecto_slug TEXT NOT NULL,
    tipo TEXT NOT NULL,
    fichero TEXT,
    commit_git TEXT,
    conversacion_id TEXT,
    mensaje_usuario TEXT,
    motivo_ia TEXT,
    tokens_input INTEGER,
    tokens_input_cached INTEGER,
    tokens_output INTEGER,
    coste_eur REAL,
    modelo TEXT,
    tool_calls_json TEXT,
    resultado TEXT
);

CREATE INDEX idx_eventos_proyecto ON eventos(proyecto_slug);
CREATE INDEX idx_eventos_fichero ON eventos(fichero);
CREATE INDEX idx_eventos_timestamp ON eventos(timestamp);
CREATE INDEX idx_eventos_conversacion ON eventos(conversacion_id);
```

**Valores de `tipo`:**
- `ia_lectura`: la IA leyó un fichero.
- `ia_escritura_propuesta`: la IA propuso una escritura.
- `ia_escritura_aplicada`: el usuario aprobó y la escritura se ejecutó.
- `ia_escritura_rechazada`: el usuario rechazó la propuesta.
- `usuario_edicion`: el usuario editó manualmente un fichero.
- `usuario_reordenacion`: el usuario reordenó capítulos manualmente.
- `sistema_init`: inicialización de proyecto.
- `sistema_restauracion`: restauración de versión.

**Tabla `conversaciones`:**
```sql
CREATE TABLE conversaciones (
    id TEXT PRIMARY KEY,
    proyecto_slug TEXT NOT NULL,
    inicio TEXT NOT NULL,
    fin TEXT,
    titulo TEXT,
    mensajes_json TEXT,
    ficheros_tocados_json TEXT,
    coste_total_eur REAL
);

CREATE INDEX idx_conv_proyecto ON conversaciones(proyecto_slug);
```

**Tabla `sesiones` (para historial de chat):**
```sql
CREATE TABLE mensajes_chat (
    id TEXT PRIMARY KEY,
    conversacion_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    rol TEXT NOT NULL,
    contenido TEXT NOT NULL,
    tool_calls_json TEXT,
    FOREIGN KEY (conversacion_id) REFERENCES conversaciones(id)
);

CREATE INDEX idx_mensajes_conv ON mensajes_chat(conversacion_id);
```

### 8.2 Registro de eventos

Toda operación significativa se registra. API interna:

```python
def registrar_evento(
    tipo: str,
    proyecto_slug: str,
    fichero: str = None,
    commit_git: str = None,
    conversacion_id: str = None,
    mensaje_usuario: str = None,
    motivo_ia: str = None,
    tokens: dict = None,
    modelo: str = None,
    tool_calls: list = None,
    resultado: str = None
):
    ...
```

### 8.3 Consultas del audit

**Endpoint `GET /api/proyecto/<slug>/audit?filtros...`:**

Parámetros de filtro:
- `fichero`: eventos que involucran ese fichero.
- `desde`, `hasta`: rango de fechas.
- `tipo`: filtrar por tipo de evento.
- `conversacion`: eventos de una conversación concreta.
- `buscar`: búsqueda de texto en `mensaje_usuario` y `motivo_ia`.

**Endpoint `GET /api/proyecto/<slug>/audit/resumen`:**
Resumen agregado del proyecto:
```json
{
  "total_eventos": 1247,
  "total_coste_eur": 12.34,
  "tokens_totales": {"input": 5600000, "output": 890000, "cached": 4200000},
  "eventos_por_tipo": {...},
  "eventos_por_mes": {...}
}
```

### 8.4 Limpieza

No hay política de borrado automático. El historial crece indefinidamente. Si en algún momento supera un tamaño razonable (>500MB), se implementa archivado manual.

---

## 9. Interfaz de usuario

### 9.1 Estructura general

Tres zonas principales en la vista autenticada:

```
┌────────────────────────────────────────────────────────────┐
│ [Proyecto: Chari ▼]    [● sync]    [usuario: inigo ▼]     │
├──────────┬────────────────────────┬─────────────────────────┤
│          │                        │                         │
│  ÁRBOL   │      ESPACIO DE        │       CHAT IA           │
│          │      TRABAJO           │                         │
│  (fija)  │                        │                         │
│          │                        │                         │
│          │                        │                         │
│          │                        │                         │
│          │                        │                         │
│          │                        │                         │
│          │                        ├─────────────────────────┤
│          │                        │ [input...] [enviar]     │
└──────────┴────────────────────────┴─────────────────────────┘
```

### 9.2 Panel izquierdo: árbol de navegación

- Carpetas del proyecto con títulos humanizados (ver mapeo en 9.6).
- Ficheros listados con etiqueta dinámica (para capítulos: "Capítulo N — Título").
- Click en fichero → se abre en el espacio central.
- Drag-and-drop de capítulos para reordenar.
- Click derecho → menú contextual: renombrar, duplicar, borrar, ver historial.
- Botón "+ Nuevo" por carpeta, con plantilla según tipo.

### 9.3 Panel central: espacio de trabajo

Tres modos de visualización según la tarea:

**Modo editor:**
- Editor Markdown (CodeMirror 6 o EasyMDE).
- Botón "Guardar" explícito o auto-save con debounce de 2 segundos.
- Indicador de estado (sin cambios / modificado / guardando / guardado).
- Conteo de palabras (total y de prosa).

**Modo diff:**
- Se activa cuando hay propuestas pendientes de la IA.
- Muestra diff unificado lado-a-lado (o línea-a-línea).
- Botones por propuesta: Aplicar / Rechazar / Editar.

**Modo historial:**
- Se activa desde "ver historial" en el menú contextual de un fichero.
- Lista cronológica de versiones.
- Click en una versión → muestra el contenido de esa versión.
- Botón "Restaurar" por versión.

### 9.4 Panel derecho: chat IA

- Historial de mensajes de la conversación actual.
- Input multilínea en la parte inferior.
- Botón enviar (también con Cmd/Ctrl+Enter).
- Indicador de "IA pensando..." cuando está procesando.
- Muestra tool calls en línea, plegables, con detalle al expandir.
- Muestra coste de la conversación acumulado.

### 9.5 Cabecera superior

- Selector de proyecto (dropdown). Al cambiar, recarga toda la UI con el nuevo proyecto.
- Indicador de sync de Git (ver 7.4).
- Menú de usuario: nombre, botón de logout.

### 9.6 Mapeo de carpetas a títulos humanos

```
00_concepto     → Concepto
01_personajes   → Personajes
02_mundo        → Mundo
03_estructura   → Estructura
04_capitulos    → Capítulos
05_control      → Control
06_revision     → Revisión
07_investigacion → Investigación
```

### 9.7 Pantalla de login

Minimalista:
- Campo usuario.
- Campo contraseña.
- Botón "Entrar".
- Mensaje de error genérico si falla.

Sin opciones de "recordarme", sin "olvidé mi contraseña" (gestión por CLI).

---

## 10. Variables de entorno

Fichero `.env` (nunca commiteado):

```
# Clave secreta de Flask
SECRET_KEY=<generada con secrets.token_hex(32)>

# Rutas
NOVELAS_ROOT=/var/novelas
APP_CONFIG_DIR=/var/lib/novela-app

# API de Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Configuración de sesión
SESSION_LIFETIME_HOURS=8

# Tasa USD→EUR para cálculo de coste
USD_TO_EUR=0.92

# Flask
FLASK_ENV=production
FLASK_DEBUG=0

# Logging
LOG_LEVEL=INFO
LOG_DIR=/var/log/novela-app
```

---

## 11. Dependencias (`requirements.txt`)

```
Flask>=3.0
Flask-Login>=0.6
anthropic>=0.40
python-frontmatter>=1.1
PyYAML>=6.0
Werkzeug>=3.0
python-dotenv>=1.0
gunicorn>=21.2
markdown>=3.5
```

---

## 12. Flujos de trabajo típicos

### 12.1 Redactar un capítulo desde idea

1. Usuario abre la app, selecciona proyecto "Chari".
2. Árbol muestra estructura. Capítulos vacíos con estado `esqueleto`.
3. Usuario click en un capítulo. Se abre (vacío).
4. Usuario escribe en chat: "Redacta este capítulo. Gorka visita al dentista. Primera sospecha. Tono contenido."
5. Chat procesa. La IA llama a `leer_fichero` en escaleta, `leer_fichero` en la ficha de Gorka, `leer_fichero` en `estilo.md`.
6. La IA propone modificación al capítulo con motivo "Redacción inicial según escaleta y estilo".
7. Panel central cambia a modo diff, mostrando el contenido propuesto.
8. Usuario revisa, pulsa "Aplicar".
9. Fichero escrito → commit Git → push → audit.
10. Panel central vuelve a modo editor con el contenido aplicado.

### 12.2 Detectar incoherencias en el borrador

1. Usuario escribe en chat: "Revisa si hay incoherencias entre los capítulos 1-10 y las fichas de personajes."
2. IA llama a `verificar_coherencia("capitulos_1_10")`.
3. La herramienta internamente recorre los capítulos, las fichas, el raccord.
4. Retorna lista de posibles incoherencias (rasgos contradictorios, cronología imposible, etc.).
5. IA presenta el informe en el chat.
6. Usuario decide qué corregir; pide correcciones puntuales.

### 12.3 Reordenar capítulos

1. Usuario arrastra capítulo 5 entre el 2 y el 3 en el árbol.
2. Frontend llama a `POST /api/proyecto/<slug>/reordenar`.
3. Backend modifica `orden.json`, commit Git, audit.
4. UI se refresca con nueva numeración.

### 12.4 Restaurar versión anterior de un fichero

1. Click derecho en un fichero → "Ver historial".
2. Panel central muestra lista de versiones.
3. Click en una versión → preview de contenido.
4. Click "Restaurar" → confirmación.
5. Backend ejecuta restauración, commit, push.
6. Panel vuelve a editor con contenido restaurado.

---

## 13. Plan de desarrollo por fases

### Fase 1: esqueleto funcional (MVP)

Objetivos:
- Login operativo.
- CRUD básico de ficheros.
- Visualización del árbol.
- Editor Markdown funcional.
- Git local con commit automático.
- Endpoint de chat IA básico con herramientas de lectura.
- Un solo proyecto activo (sin multi-proyecto todavía).

Tiempo estimado: 2-3 semanas a dedicación media.

### Fase 2: IA activa con tool use de escritura

Objetivos:
- Tool use completo incluyendo escritura.
- Sistema de diff y aprobación.
- Caché de contexto por bloques.
- Audit trail completo.
- Push automático a Git remoto.

Tiempo estimado: 2-3 semanas.

### Fase 3: Multi-proyecto y sagas

Objetivos:
- Selector de proyecto.
- Soporte de sagas con canon compartido.
- Ensamblado de contexto en tres capas.

Tiempo estimado: 1-2 semanas.

### Fase 4: Pulido de UI y flujos

Objetivos:
- Drag-and-drop para reordenar.
- Historial visual por fichero.
- Indicador de sync.
- Conteo de palabras, preview Markdown.
- Plantillas al crear ficheros nuevos.

Tiempo estimado: 2 semanas.

### Fase 5 (opcional): Exportación

Objetivos:
- Compositor de EPUB/DOCX/PDF desde `orden.json` + ficheros de capítulo.
- Plantillas de estilo configurables.

Tiempo estimado: 2 semanas.

---

## 14. Lo que queda fuera del MVP

Explícitamente, estas funcionalidades **no** se implementan en las primeras versiones. Se pueden añadir después si hay demanda real de uso:

- 2FA integrado en la aplicación (el operador lo resuelve a nivel infraestructura si lo necesita).
- Múltiples usuarios o colaboración concurrente.
- Modo offline o sincronización desconectada.
- Exportación a formatos comerciales avanzados.
- Estadísticas narrativas complejas (ritmo, longitud de escenas, análisis de voz).
- Integración con herramientas externas (Scrivener, Word).
- Backup automático a servicios en la nube distintos del Git remoto.
- Notificaciones push.
- API REST pública para integración con scripts externos.

---

## 15. Consideraciones operativas

### 15.1 Logging

Tres niveles de log diferenciados:

- **Audit log** (SQLite): eventos sobre contenido narrativo. Permanente.
- **Access log** (fichero): logins, logouts, accesos. Rotación semanal, retención mensual.
- **Application log** (fichero): errores, warnings, operaciones Git, llamadas a API. Rotación diaria, retención semanal.

### 15.2 Errores de la API de Anthropic

Gestionar con retry y backoff exponencial:
- Rate limit (429): 3 reintentos con backoff (1s, 2s, 4s).
- Server error (5xx): 2 reintentos con backoff.
- Otros errores: fallar inmediatamente, mostrar al usuario.

Todos los errores se registran en application log.

### 15.3 Seguridad de `tool_use`

Validaciones obligatorias antes de ejecutar cualquier herramienta que reciba rutas:

1. La ruta es relativa al proyecto activo.
2. Normalizar la ruta (resolver `..`, `.`).
3. Verificar que la ruta normalizada sigue dentro del directorio del proyecto.
4. Rechazar cualquier ruta con componentes absolutos (`/etc/passwd`, etc.).

### 15.4 Concurrencia

Único usuario, sesión única, no hay concurrencia real. Pero para evitar problemas con operaciones Git simultáneas:

- Cada operación de escritura adquiere un lock del proyecto.
- Si hay lock activo, la segunda operación espera (máximo 10 segundos) o falla.

### 15.5 Manejo de ficheros grandes

Un capítulo típico son 10-30 KB. Una biblia completa 50-100 KB. No se esperan ficheros grandes.

Límite soft: 1 MB por fichero. Si se supera, warning en log pero no bloqueo.

### 15.6 Backup del SQLite

El fichero `audit.db` se copia a una ubicación de backup cada 24 horas. Ruta configurable. Retención de 30 días.

---

## 16. Inicialización de una instalación nueva

Secuencia para arrancar la aplicación en un servidor limpio:

1. Crear directorios:
   ```
   mkdir -p /var/novelas/{independientes,sagas}
   mkdir -p /var/lib/novela-app/logs
   chown -R usuario_app:usuario_app /var/novelas /var/lib/novela-app
   chmod 750 /var/novelas /var/lib/novela-app
   ```

2. Clonar el código de la aplicación e instalar dependencias:
   ```
   git clone <url_repo_app> /opt/novela-app
   cd /opt/novela-app
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Configurar `.env` con valores de producción.

4. Crear usuario inicial:
   ```
   python manage.py set_password
   ```

5. Inicializar base de datos:
   ```
   python manage.py init_db
   ```

6. Configurar systemd service (archivo `/etc/systemd/system/novela-app.service`):
   ```ini
   [Unit]
   Description=Novela App
   After=network.target
   
   [Service]
   User=usuario_app
   WorkingDirectory=/opt/novela-app
   Environment="PATH=/opt/novela-app/venv/bin"
   EnvironmentFile=/opt/novela-app/.env
   ExecStart=/opt/novela-app/venv/bin/gunicorn -w 3 -b 127.0.0.1:8000 wsgi:app
   Restart=always
   
   [Install]
   WantedBy=multi-user.target
   ```

7. Habilitar y arrancar:
   ```
   systemctl enable novela-app
   systemctl start novela-app
   ```

8. Configurar proxy inverso (Cloudflare Tunnel / nginx / lo que el operador use) apuntando a `127.0.0.1:8000`.

---

## 17. Resumen de decisiones clave

Para referencia rápida durante la implementación:

| Decisión | Valor |
|---|---|
| Lenguaje backend | Python 3.11+ |
| Framework | Flask |
| Servidor WSGI | Gunicorn |
| Frontend | HTML+CSS+JS vanilla o Alpine.js/HTMX |
| Editor Markdown | CodeMirror 6 o EasyMDE |
| Base de datos | SQLite |
| Autenticación | Flask-Login + werkzeug hashing |
| Usuarios | Uno solo, en users.json |
| Control de versiones | Git vía subprocess |
| Git remoto | Sí, con push automático |
| IA | API de Anthropic, SDK oficial |
| Modelo por defecto | claude-sonnet-4-6 |
| Caché | Prompt caching con `cache_control` |
| Límite tool calls por turno | 5 |
| Diff antes de aplicar | Obligatorio para escrituras de IA |
| Timeout de sesión | 8 horas con renovación sliding |
| Single user | Sí |
| Multi-proyecto | Sí, con independientes y sagas |
| Exportación EPUB/PDF/DOCX | Fase 5, no MVP |

---

## 18. Orden de implementación recomendado

Para Claude Code, si va a implementar esto paso a paso, el orden óptimo es:

1. Estructura básica de directorios y `requirements.txt`.
2. Configuración (`.env`, `config/`) y carga de settings.
3. Módulo de autenticación (`auth/`): login, logout, protección de rutas, `manage.py set_password`.
4. Módulo de ficheros (`files/`): parsers, endpoints CRUD, `orden.json`.
5. Módulo de versionado (`versioning/`): wrapper sobre Git, commits automáticos.
6. Módulo de audit (`audit/`): schema SQLite, registro de eventos.
7. Módulo de IA (`ai/`): cliente Anthropic, ensamblado de contexto, tool use sin escritura.
8. Herramientas de escritura con sistema de propuesta/aprobación.
9. Frontend: árbol, editor, chat, diff viewer.
10. Multi-proyecto y soporte de sagas.
11. Pulido, testing, documentación final.

Cada paso debería dejar la aplicación en un estado funcional aunque incompleto, de forma que se pueda probar incrementalmente.

---

## 19. Cierre

Este documento es suficiente para que un desarrollador (humano o asistente de IA como Claude Code) implemente la aplicación desde cero. Si durante la implementación aparecen ambigüedades o decisiones no cubiertas, se resuelven por prioridad en este orden:

1. Respeto a los ocho principios rectores.
2. Simplicidad sobre completitud.
3. Funcionalidad del MVP sobre adornos.
4. Seguridad mínima (login, validación de rutas).
5. Mantenibilidad del código.

Cualquier desviación sustancial respecto a este documento debe quedar documentada en los comentarios del código y registrada como decisión en el README del proyecto.
