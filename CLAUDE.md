# gunovel — reglas del dominio para Claude Code

Este repositorio contiene la aplicación **novela-app** (Flask + UI editorial) y el directorio **novelas/** donde viven todas las novelas del autor como subdirectorios de un monorepo.

Lee este fichero **completo** antes de trabajar sobre cualquier novela. Las reglas son innegociables: desviarse de ellas introduce complejidad que después cuesta mucho revertir.

---

## 1. Los 8 principios rectores

Aplican a toda operación sobre `novelas/`:

1. **Una entidad, un fichero.** Cada capítulo, personaje, lugar tiene exactamente un `.md`. Versiones anteriores viven en Git, nunca como ficheros paralelos (`cap03_v2.md` está prohibido).
2. **Nombre estable; título y posición son capas separadas.** El nombre del fichero (`jose_luis.md`) es identificador permanente. El título humano vive dentro del fichero. La posición en la secuencia narrativa vive en `03_estructura/orden.json`.
3. **Numeración externa.** Los ficheros no contienen su número. "Capítulo 3" se calcula desde `orden.json`.
4. **Los capítulos son prosa pura.** Cabecera YAML mínima + prosa publicable. No metacomentarios, no notas embebidas.
5. **Fuente única de verdad.** Cada hecho narrativo (rasgo de personaje, propiedad de un lugar, decisión editorial) vive en exactamente un fichero. Los demás lo referencian, nunca lo duplican.
6. **La IA propaga y respeta el canon.** Al modificar un fichero, evalúa qué otros necesitan actualización coordinada y aplica esos cambios en la misma sesión.
7. **Multi-proyecto con canon compartido para sagas.** Novelas independientes en `novelas/independientes/`, sagas en `novelas/sagas/` con `00_canon_compartido/`.
8. **Acceso protegido por login.** La app web requiere autenticación. No aplicable a operaciones directas de Claude Code sobre el disco.

---

## 2. Estructura de una novela

```
novelas/independientes/<slug_novela>/
├── 00_concepto/
│   ├── premisa.md
│   ├── sinopsis.md
│   └── tesis.md
├── 01_personajes/
│   └── <slug_personaje>.md
├── 02_mundo/
│   ├── worldbuilding.md
│   ├── glosario.md
│   └── <slug_lugar>.md
├── 03_estructura/
│   ├── actos.md
│   ├── escaleta.md
│   ├── cronologia.md
│   ├── pov.md
│   ├── relaciones.md
│   └── orden.json          <-- fuente de verdad del orden
├── 04_capitulos/
│   └── <slug_capitulo>.md
├── 05_control/
│   ├── estilo.md
│   ├── raccord.md
│   ├── bitacora.md
│   ├── plan_autonomo.md    <-- si existe, es tu lista de tareas
│   ├── preguntas_autor.md  <-- decisiones pendientes del autor
│   ├── feedback_autor.md   <-- correcciones previas del autor (no las repitas)
│   └── golden_reference.md <-- si existe, es la referencia de voz
├── 06_revision/
│   ├── plan_correcciones.md
│   └── notas_editoriales.md
└── 07_investigacion/
    └── fuentes.md
```

Sagas: misma estructura por libro bajo `novelas/sagas/<slug_saga>/<slug_libro>/`, más `novelas/sagas/<slug_saga>/00_canon_compartido/` con personajes/, mundo/, estilo.md, reglas_universo.md, cronologia_saga.md, bitacora_saga.md.

---

## 3. Convenciones de slug

- Solo ASCII minúsculas, dígitos y guiones bajos.
- Sin espacios, sin tildes, sin eñes, sin mayúsculas.
- Estables: una vez asignados no cambian. Si el autor pide renombrar, usa `git mv` y actualiza todos los ficheros que referencian el slug anterior.
- Descriptivos: `jose_luis.md`, no `personaje_principal.md`.

---

## 4. Frontmatter YAML por tipo

### Capítulo (`04_capitulos/*.md`)

```yaml
---
slug: jose_luis
personajes: [oli, jose_luis]
pov: oli
estado: borrador_v2
---
```

Estados válidos: `esqueleto | borrador | borrador_v2 | revisado | cerrado`.

**IMPORTANTE**: nunca modifiques un capítulo con estado `revisado` o `cerrado` sin autorización explícita del autor. Si necesitas cambiarlo, añade la tarea a `06_revision/plan_correcciones.md` y deja que el autor decida.

### Ficha de personaje (`01_personajes/*.md`)

```yaml
---
slug: jose_luis
tipo: personaje
aparece_en: [jose_luis, el_hallazgo]
rol: principal    # principal | secundario | terciario | mencionado
---
```

### Ficha de lugar (`02_mundo/*.md`)

```yaml
---
slug: faro_castro
tipo: lugar
aparece_en: [jose_luis, el_hallazgo]
---
```

---

## 5. Reglas de escritura de prosa

- **No referencias numéricas a capítulos en la prosa**: "como vimos en el capítulo 3" está prohibido. Usa referencias narrativas: "la noche en el faro", "cuando Oli conoció a José Luis".
- **No inventes hechos de canon** sin consultar las fichas. Si necesitas un detalle no documentado, primero proponlo como añadido a la ficha correspondiente y luego úsalo en la prosa.
- **Respeta la voz del autor**: si existe `05_control/golden_reference.md`, léelo antes de redactar y úsalo como brújula de tono, ritmo y voz. Si existe `05_control/feedback_autor.md`, léelo y no repitas errores que el autor ya te corrigió.
- **Prosa pura en capítulos**: ni notas ni metacomentarios dentro del cuerpo.
- **Cada capítulo debe abrir con un gancho** (tiempo, lugar o estado emocional) y cerrar con algo que sostenga al lector al siguiente.

---

## 6. Orden de capítulos (`orden.json`)

```json
{
  "capitulos": [
    {"slug": "llegada_castro"},
    {"slug": "primera_noche"}
  ],
  "prologo": {"slug": "prologo", "etiqueta": "Prólogo"},
  "epilogo": {"slug": "epilogo", "etiqueta": "Epílogo"}
}
```

- `prologo` y `epilogo` son opcionales y no cuentan para la numeración.
- Si añades un capítulo nuevo redactado, también añádelo a `orden.json` en la posición correcta.

---

## 7. Git y commits

Cada operación sobre una novela debe traducirse en un commit con mensaje estructurado. Esto lo gestiona la app web para ediciones humanas; para tus ediciones desde Claude Code, usa manualmente `git add <fichero> && git commit -m "[IA] <slug_proyecto>/<ruta>: <motivo_breve>"`.

Convención de prefijos:

- `[IA] ...` — cambios que tú has hecho.
- `[YO] ...` — cambios que ha hecho el autor manualmente.
- `[SYS] ...` — cambios automáticos (inicialización, migración, restauración).

Haz commits **pequeños y frecuentes**: un commit por propuesta coherente, no un commit gigante al final. Auto-push a `origin/main` está activo.

---

## 8. Tools MCP disponibles

Este repo expone un MCP server local (`mcp__gunovel`) con tools específicas del dominio:

- **`auditar_capitulo(proyecto_slug, slug)`** — ejecuta auditoría determinista sobre un capítulo: repeticiones, tics, verbos dicendi, erratas, longitud, coherencia.
- **`verificar_coherencia(proyecto_slug, ambito)`** — chequeos de coherencia de metadata y canon.
- **`resumen_canon_actual(proyecto_slug)`** — resumen compacto: premisa, sinopsis recortada, personajes principales, lugares, último capítulo redactado, siguiente a redactar.
- **`ver_capitulos_adyacentes(proyecto_slug, slug)`** — capítulo anterior completo + escaleta del siguiente.
- **`obtener_info_capitulo(proyecto_slug, slug)`** — título, etiqueta UI, posición, personajes, POV, estado.
- **`listar_proyectos()`** — novelas independientes y sagas con sus libros.

Úsalas cuando tengas sentido; para lectura/escritura genérica de ficheros usa Read/Write/Edit como en cualquier proyecto.

---

## 9. Orden de trabajo típico en una novela

Para redactar un capítulo desde escaleta:

1. `resumen_canon_actual(proyecto)` — ubícate.
2. Lee la entrada de escaleta del capítulo (`03_estructura/escaleta.md`) y de los dos anteriores.
3. Lee las fichas de personajes presentes en la cabecera.
4. Lee el capítulo anterior completo (prosa) para cohesión.
5. Lee `05_control/estilo.md` y, si existe, `golden_reference.md`.
6. Redacta el capítulo con Write o Edit en `04_capitulos/<slug>.md`.
7. Actualiza `03_estructura/orden.json` si el capítulo es nuevo.
8. `auditar_capitulo(proyecto, slug)` — valida tu propio trabajo.
9. Si hay hallazgos graves (repeticiones >= 5, dicendi color > 50%, coherencia con gravedad alta), corrige antes de dar por hecho.
10. Actualiza `05_control/raccord.md` con detalles que se siembran para capítulos posteriores.
11. Commit.

---

## 10. Trabajo en modo autónomo

Si el autor te ha pedido trabajar en modo autónomo sobre un proyecto:

1. Busca `05_control/plan_autonomo.md` en el proyecto. Si no existe, créalo tras entender el estado actual del canon.
2. Elige la siguiente tarea marcada `[ ]`.
3. Ejecútala.
4. Marca la tarea como `[x]` (hecha), `[?]` (bloqueada por decisión del autor) o `[!]` (error).
5. Si necesitas una decisión del autor, añádela a `05_control/preguntas_autor.md` con el formato del propio fichero y detente (no inventes la decisión).
6. Commit por tarea.
7. Cuando no queden tareas `[ ]`, emite un mensaje final indicando que has terminado.

---

## 11. Reglas de seguridad

- **Nunca** edites ficheros dentro de `.git/`, `novela-app/.venv/`, `novela-app/.env`, `__pycache__/`.
- **Nunca** edites capítulos con estado `revisado` o `cerrado` sin autorización explícita del autor en un mensaje de esta sesión.
- **Nunca** hagas `git push --force`. Si hay conflicto, detente y pregunta.
- **Nunca** borres un fichero del canon sin comprobar que nada lo referencia.
- Si vas a hacer un cambio estructural grande (reescribir un acto, renombrar un personaje principal, cambiar POV global), **pregunta antes** al autor mediante `05_control/preguntas_autor.md`.

---

## 12. Código de la app

Si el autor te pide trabajar sobre la propia aplicación (en `novela-app/`):

- Python 3.11+, Flask, SQLite, `anthropic` SDK.
- Los módulos viven en `novela-app/app/`.
- Dependencias en `novela-app/requirements.txt`.
- Virtualenv en `novela-app/.venv/`.
- Variables de entorno en `novela-app/.env` (nunca commitees este fichero).
- Lee `novela-app/README.md` para el estado actual.
- El código de la app es independiente del contenido de las novelas. No mezcles trabajo de una novela con refactor del código.
