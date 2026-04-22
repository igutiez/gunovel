# Novela App

Aplicación web de escritura de novelas asistida por Claude (API de Anthropic). Respeta los ocho principios rectores de `../especificacion_tecnica_novela_app.md`.

---

## Arranque en desarrollo (local, macOS)

```bash
cd novela-app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Configurar entorno
cp .env.example .env
# edita .env: SECRET_KEY, NOVELAS_ROOT, APP_CONFIG_DIR, ANTHROPIC_API_KEY

.venv/bin/python3 manage.py init_db            # crea audit.db
.venv/bin/python3 manage.py set_password       # crea usuario único
.venv/bin/python3 manage.py new_project chari "Chari"    # una novela de prueba
.venv/bin/python3 wsgi.py                      # arranca http://127.0.0.1:8000/
```

---

## Estado por fase de la spec

### Fase 1 – MVP funcional
- Login/logout con `pbkdf2:sha256`, sesión sliding de 8 h, access log rotado, `ProxyFix`.
- CRUD de ficheros con escritura atómica y prevención de path traversal.
- Editor Markdown (EasyMDE) con auto-save a 2 s, contador de palabras del cuerpo.
- Árbol del proyecto con carpetas humanizadas y numeración automática desde `orden.json`.
- Git local con commit automático por cada escritura, mensajes `[IA]`/`[YO]`/`[SYS]`.

### Fase 2 – IA activa con tool use de escritura
- Cliente Anthropic con **retry/backoff** (429 → 1s/2s/4s; 5xx → 1s/2s).
- **10 herramientas** expuestas: `leer_fichero`, `listar_ficheros_proyecto`, `buscar_texto`, `consultar_grafo_relaciones`, `obtener_info_capitulo`, `verificar_coherencia` (con chequeos reales), `leer_canon_saga`, `modificar_fichero`, `crear_fichero`, `reordenar_capitulos`, `actualizar_grafo_relaciones`.
- Las herramientas de escritura **registran propuestas** persistidas en SQLite; el usuario las ve con **diff unified coloreado** y decide: **Aplicar / Editar / Rechazar** (por propuesta o en bloque).
- **Contexto en 3 capas con `cache_control`** (capa estable con TTL 1 h).
- **Truncado** de resultados de tools a 8 kB para no reventar el contexto.
- **Resumen automático con Haiku** cuando el historial excede la ventana de 50 mensajes.
- Coste por turno registrado y visible, acumulado por conversación.
- Commit `[IA] ruta: motivo` automático al aplicar cada propuesta.

### Fase 3 – Multi-proyecto y sagas
- Proyectos **independientes** y **sagas con canon compartido** (estructura `00_canon_compartido/` con personajes/, mundo/, cronología, reglas, estilo, bitácora).
- Un libro de saga hereda automáticamente estilo, reglas del universo, cronología y fichas del canon.
- Endpoints y CLI para crear saga y añadir libros.
- Selector de proyecto en UI con sagas desplegadas.
- Slugs compuestos usan `::` en las URLs (`alianza::libro_1_senales`).

### Fase 4 – Pulido de UI
- **Drag-and-drop** para reordenar capítulos en el árbol.
- **Menú contextual** (click derecho): abrir, ver historial, renombrar, borrar.
- **Modo historial** en el panel central con lista de commits, preview y restaurar.
- **Modo audit** con filtros (fichero, tipo, texto) y resumen agregado (eventos, coste total, tokens).
- Botón **"+ Nueva novela"**, **"+ Saga"**, **"+ Libro"** (contextual), **"+"** por carpeta con plantillas según tipo.
- Indicador de estado Git (verde/amarillo/rojo) con información de commits pendientes.

### Fase 5 – Exportación (opcional)
- **EPUB** válido con `ebooklib`, compuesto desde `orden.json` + capítulos, CSS propio, TOC navegable.

### Cross-cutting
- **Validación de frontmatter** al guardar (slugs coherentes, estados válidos).
- **Verificación de coherencia** real: metadata, `aparece_en` vs capítulos listados, POV con ficha, personajes del texto no declarados.
- **Grafo de relaciones** editado estructuralmente (por secciones), no append ciego.
- **Script de backup SQLite** con retención configurable (cron-ready en `scripts/backup_audit_db.py`).
- **Deshacer** último commit (`git revert HEAD`) desde la UI.

---

## Multi-modelo

La app usa tres modelos de Claude según la tarea:

| Modelo | Uso | Coste aprox. |
|---|---|---|
| `claude-haiku-4-5` | Verificación rápida, resumen de historial antiguo, búsqueda guiada | $1/$5 MTok |
| `claude-sonnet-4-6` (default) | Redacción, mayoría de interacciones | $3/$15 MTok |
| `claude-opus-4-7` | Revisión editorial completa, capítulos pivote, establecimiento de biblia | $15/$75 MTok |

Selector en el panel del chat. El default del proyecto se lee de `.novela-config.json`.

---

## Git remoto

Configurable desde la UI (botón **"Git remoto"**) o editando `.novela-config.json` → `git.remoto_url` y `git.auto_push`.

- **SSH** (recomendado): tener la clave cargada en `ssh-agent` y dada de alta en GitHub/GitLab.
- **HTTPS**: configurar credential helper (`git config --global credential.helper osxkeychain`). Usar token personal en vez de contraseña.

Con `auto_push: true`, cada commit encola un `git push` en background que no bloquea la UI. Los fallos quedan registrados en el indicador de sync.

---

## Comandos CLI

```bash
python manage.py set_password                           # crea/cambia el usuario único
python manage.py init_db                                # inicializa audit.db
python manage.py new_project <slug> [nombre]            # novela independiente
python manage.py new_saga <slug> [nombre]               # saga con canon compartido vacío
python manage.py add_book <saga_slug> <libro_slug> <nombre> [orden]  # libro a saga
python scripts/backup_audit_db.py [--dir ...] [--retain 30]          # backup SQLite
```

---

## Estructura

```
novela-app/
├── app/
│   ├── config.py              # carga .env
│   ├── auth/                  # login, users.json, access log
│   ├── files/                 # parser, CRUD, árbol, proyectos, sagas
│   ├── versioning/            # git_ops (init/commit/push/revert), rutas
│   ├── audit/                 # SQLite: eventos, conversaciones, mensajes, propuestas
│   ├── ai/
│   │   ├── tools.py           # 11 herramientas para la IA
│   │   ├── tool_use.py        # bucle de tool use, retry/backoff, cache control
│   │   ├── context_builder.py # 3 capas, incluye canon de saga
│   │   ├── propuestas.py      # store SQLite + diff unified
│   │   ├── resumen.py         # resumen con Haiku
│   │   ├── coherencia.py      # verificar_coherencia real
│   │   ├── grafo.py           # edición estructural de relaciones.md
│   │   ├── pricing.py         # coste por modelo
│   │   └── routes.py          # /chat, /propuesta/...
│   └── main/                  # /app, /api/proyecto/<slug>/export/epub
├── static/{css,js}            # UI de 3 paneles
├── templates/                 # base, login, app
├── scripts/backup_audit_db.py
├── manage.py                  # CLI
└── wsgi.py
```

---

## Lo que queda fuera

- **Exportación DOCX/PDF**: EPUB está implementado; DOCX/PDF son trivialmente añadibles con `python-docx` y `weasyprint` pero no vienen de serie.
- **2FA / múltiples usuarios**: por diseño (single-user).
- **Embeddings para búsqueda semántica**: no pedidos en la spec base.
- **Offline / sincronización desconectada**: no pedido.

---

## Notas operativas

- **Seguridad de rutas:** validación contra path traversal en todas las operaciones.
- **Lock por proyecto:** las escrituras y push Git se serializan por proyecto.
- **Propuestas persistidas:** sobreviven reinicios del server (tabla `propuestas`).
- **Backup:** `scripts/backup_audit_db.py` copia consistentemente el SQLite con `Connection.backup()`.
