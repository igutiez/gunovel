# Guía de documentos para escribir una novela

*Versión orientada a flujo de co-escritura con IA vía API.*

---

## 0. Filosofía

Los documentos no son burocracia: son **herramientas de control**. Su función triple es:

1. **Pensar antes de escribir**, para no tirar 30.000 palabras por un giro mal planificado.
2. **Mantener consistencia** en proyectos largos (47 capítulos, trilogías).
3. **Servir de contexto a la IA** cuando se delega redacción, revisión o chequeo.

Principio clave: **si un documento no se usa, sobra**. Mejor tres documentos vivos que quince olvidados en una carpeta.

---

## 1. Estructura del proyecto en carpetas

Estructura recomendada, compatible con la nomenclatura que ya usas (`norte_*.md`, `scifi_*.md`, `elena_vidal_*.md`):

```
novela/
├── 00_concepto/
│   ├── premisa.md
│   ├── sinopsis.md
│   └── tesis.md
├── 01_personajes/
│   ├── biblia_personajes.md
│   └── relaciones.md
├── 02_mundo/
│   ├── worldbuilding.md
│   ├── glosario.md
│   └── mapa.md              (opcional)
├── 03_estructura/
│   ├── actos.md
│   ├── escaleta.md          (plan capítulo a capítulo)
│   ├── cronologia.md
│   └── pov.md
├── 04_capitulos/
│   ├── cap01.md
│   ├── cap02.md
│   └── ...
├── 05_control/
│   ├── estilo.md            (guía de voz y prosa)
│   ├── raccord.md
│   └── bitacora.md          (decisiones estructurales)
├── 06_revision/
│   ├── plan_correcciones.md
│   └── notas_editoriales.md
└── 07_investigacion/
    ├── fuentes.md
    └── referencias/
```

Todos los archivos en Markdown plano. Un solo formato, sin Word ni Notion: legible por humanos y por la IA sin conversión.

---

## FASE 1 — CONCEPCIÓN

### 1.1 Premisa (logline)

**Qué es:** el núcleo de la novela en una o dos frases. Protagonista + objetivo + obstáculo + riesgo.

**Debe contener:**
- Quién es el protagonista (no por nombre, por rol).
- Qué busca o enfrenta.
- Qué se opone.
- Qué hay en juego.

**NO debe contener:**
- Adjetivos de marketing ("trepidante", "inolvidable").
- Spoilers del desenlace.
- Lista de temas.
- Más de dos frases.

**Ejemplo (estilo *Lote 7*):**
> Un ingeniero de validación en un laboratorio farmacéutico descubre que su empresa lleva años ocultando contaminación por endotoxinas en cartuchos de anestesia dental, y debe decidir entre denunciar —arruinando su carrera y la de sus compañeros— o callar mientras los pacientes siguen reaccionando.

**Uso con IA:** va siempre en el system prompt. Es la brújula para cualquier decisión de trama.

---

### 1.2 Sinopsis extendida

**Qué es:** resumen narrativo completo de 1–3 páginas (500–1.500 palabras) que cuenta **toda la novela, incluido el final**.

**Debe contener:**
- Planteamiento, detonante, desarrollo, clímax, resolución.
- Subtramas principales.
- Arco de cada protagonista.
- Revelaciones clave y en qué momento ocurren.

**NO debe contener:**
- Subtramas menores o secundarias de color.
- Descripciones sensoriales o atmosféricas.
- Diálogo reproducido.
- Ambigüedad: aquí se cuenta el final sin reservas.

**Uso con IA:** contexto permanente. Cuando la IA redacta un capítulo, necesita saber hacia dónde va la historia aunque el lector no lo sepa.

---

### 1.3 Documento de tesis / tema

**Qué es:** qué trata la novela **por debajo de la trama**. Una o dos páginas.

**Debe contener:**
- Pregunta central que la novela plantea (no responde necesariamente).
- Tensiones temáticas (p. ej., en *La cadena del silencio*: institución vs. verdad original).
- Qué NO es la novela (útil para evitar derivas; ej. "no es anti-Iglesia, es crítica al modelo institucional").

**NO debe contener:**
- Moraleja.
- Lista de "lo que el lector aprenderá".
- Preguntas retóricas vacías.

**Uso con IA:** imprescindible para que la IA no derive hacia lugares comunes. Sin tesis, escribe genérico.

---

### 1.4 Referentes de tono (opcional pero útil)

**Qué es:** lista corta de autores/obras cuyo tono, estructura o ritmo sirven de referencia.

**Debe contener:**
- 3–5 referentes máximo, con una línea explicando **qué** se toma de cada uno.
- Ejemplo (estilo *Alianza*): George R.R. Martin → consecuencias; Michael Crichton → verosimilitud técnica; Dan Brown → ritmo y ganchos.

**NO debe contener:**
- Lista larga de "libros que me gustan".
- Imitación: se toma una dimensión concreta de cada uno, no el estilo completo.

---

## FASE 2 — PERSONAJES

### 2.1 Biblia de personajes

**Qué es:** ficha por personaje. Protagonistas y secundarios recurrentes; no para figurantes.

**Debe contener por cada personaje:**
- **Identidad:** nombre, edad, origen geográfico, ocupación.
- **Función narrativa:** qué papel cumple (antagonista, mentor, interés amoroso, contrapunto ideológico…).
- **Objetivo:** qué quiere conscientemente en la novela.
- **Necesidad:** qué necesita en realidad (normalmente distinto del objetivo).
- **Conflicto interno:** contradicción central que lo mueve.
- **Arco:** de dónde parte, a dónde llega, qué lo transforma.
- **Voz:** 3–5 rasgos concretos del habla (léxico, muletillas, longitud de frase, registros). Ejemplo útil: "Esti guarda y archiva, nunca descarta".
- **Tics físicos / gestuales:** 1–2, no más.
- **Qué sabe y qué no sabe** en cada momento clave de la trama.

**NO debe contener:**
- Tests de personalidad (MBTI, eneagrama, horóscopo). No sirven narrativamente.
- Backstory exhaustiva que no va a entrar en el texto.
- Descripción física milimétrica si no es relevante.
- Datos de color irrelevantes al arco ("le gusta el café solo").
- Lista de aficiones sin función.

**Formato sugerido:**

```markdown
## Gorka Lekabe
- **Función:** protagonista, punto de vista principal.
- **Objetivo:** aprobar el lote 7 y terminar la jornada.
- **Necesidad:** recuperar el sentido ético que perdió al aceptar ascensos.
- **Conflicto interno:** lealtad a la empresa vs. responsabilidad profesional.
- **Arco:** complicidad pasiva → duda → denuncia → consecuencias.
- **Voz:** técnico, elíptico bajo presión, evita adjetivos, recurre a normativa cuando
  quiere ganar tiempo.
- **Gestos:** se toca el reloj antes de mentir.
- **Sabe en cap 1:** que hay desviaciones en el LAL test.
- **No sabe hasta cap 14:** que Dirección lo supo antes que él.
```

**Uso con IA:** cuando se redacta una escena, se pasan las fichas **solo** de los personajes presentes. No se mete la biblia entera.

---

### 2.2 Matriz de relaciones

**Qué es:** tabla o lista que describe qué siente/sabe cada personaje respecto a cada otro.

**Debe contener:**
- Par de personajes → naturaleza de la relación → evolución a lo largo de la novela.
- Secretos entre personajes (quién oculta qué a quién).

**NO debe contener:**
- Relaciones con figurantes.
- Descripciones redundantes con la biblia.

---

## FASE 3 — MUNDO

### 3.1 Worldbuilding

**Qué es:** documento con las **reglas del mundo**. Fundamental en sci-fi/fantasy (*Alianza*), opcional pero útil en thriller contemporáneo (*Lote 7* necesita reglas del laboratorio, auditorías, FDA/EMA).

**Debe contener:**
- Reglas físicas, tecnológicas o sociales que condicionan la trama.
- Jerarquías, castas, instituciones relevantes.
- Historia previa **solo** si impacta en la trama presente.
- Qué pueden y no pueden hacer los personajes por las reglas del mundo.

**NO debe contener:**
- Infodump que piensas copiar al texto. El worldbuilding es para **ti**, no para el lector. El lector solo debe ver la punta del iceberg.
- Enciclopedia completa de un mundo del que solo se verá el 5%.
- Inconsistencias no marcadas. Si hay contradicción, se anota explícitamente que es cuestión abierta.

**Regla de oro:** si una regla no restringe ni impulsa la trama, no es worldbuilding, es decoración.

---

### 3.2 Glosario

**Qué es:** términos propios, jerga técnica, idioma inventado, acrónimos.

**Debe contener:**
- Término → definición de una línea → primera aparición (capítulo).
- Nota si el término evoluciona de significado.

**NO debe contener:**
- Palabras comunes.
- Términos usados una sola vez que se explican en el texto.

**Uso con IA:** imprescindible en sci-fi/thriller técnico. Evita que la IA invente terminología paralela a la tuya.

---

### 3.3 Investigación

**Qué es:** carpeta con fuentes consultadas (artículos, libros, entrevistas, fotos).

**Debe contener:**
- Cita de la fuente.
- Extracto o resumen con la información relevante.
- Dónde se usa en la novela.

**NO debe contener:**
- Dumps enteros de Wikipedia sin filtrar.
- Fuentes no verificadas tratadas como canon.

---

## FASE 4 — ESTRUCTURA

### 4.1 Esqueleto de actos

**Qué es:** vista macro de la novela en 3, 4 o 5 actos.

**Debe contener:**
- Por cada acto: función narrativa, punto de partida, punto de salida.
- Puntos de giro (detonante, primer giro, punto medio, clímax, resolución).

**NO debe contener:**
- Detalle de escenas (eso es la escaleta).
- Prosa.

---

### 4.2 Escaleta (plan capítulo a capítulo)

**Qué es:** el documento más importante junto a la biblia de personajes. Plan de cada capítulo en 5–15 líneas.

**Debe contener por capítulo:**
- Número y título provisional.
- POV (quién narra).
- Ubicación y momento temporal.
- Personajes presentes.
- **Función narrativa:** qué avanza, qué revela, qué información nueva recibe el lector.
- Gancho de cierre.
- Conexión con capítulos anteriores y posteriores (qué semilla planta, qué semilla recoge).

**NO debe contener:**
- Prosa.
- Diálogos reproducidos (máximo una línea clave si define el capítulo).
- Descripciones sensoriales.

**Formato:**

```markdown
## Cap 07 — "El embudo"
- **POV:** Elena.
- **Escenario:** Parkes, sala de control, noche.
- **Presentes:** Elena, Ariza, Alexei.
- **Función:** revelar que la señal contiene una séptima capa no prevista.
  Primera fisura pública entre Elena y Alexei.
- **Siembra:** paranoia sobre propaganda en la capa 7.
- **Recoge:** la duda técnica introducida en cap 4.
- **Gancho:** Ariza pide hablar con Elena a solas.
```

**Uso con IA:** cuando la IA redacta un capítulo, se le pasa la entrada de la escaleta de **ese** capítulo + las de los dos anteriores y el siguiente. Nada más de la escaleta.

---

### 4.3 Cronología

**Qué es:** línea temporal con fechas, edades y hechos anteriores al inicio de la novela.

**Debe contener:**
- Fecha (real o relativa) → evento → capítulo donde aparece o se menciona.
- Edades de personajes clave en cada fecha relevante.
- Eventos del pasado que se revelan durante la novela, con su orden real vs. orden de revelación.

**NO debe contener:**
- Eventos irrelevantes.
- Narrativa.

**Útil para:** detectar agujeros ("si X nació en 1982 y tiene 30 en el cap 5, estamos en 2012, pero en cap 3 mencionas un iPhone 14").

---

### 4.4 Plan de POV

**Qué es:** quién narra qué. Especialmente si hay múltiples puntos de vista (caso de *NORTE*, con Oli en impares y Esti en pares).

**Debe contener:**
- Regla de asignación (cap impar Oli / par Esti).
- Qué sabe cada narrador en cada momento.
- Voz de cada narrador (resumen; el detalle va en la biblia).

**NO debe contener:**
- Repetición de la biblia de personajes.

---

## FASE 5 — CONTROL DE ESCRITURA

### 5.1 Guía de estilo

**Qué es:** reglas de prosa y voz del libro. 1–2 páginas.

**Debe contener:**
- Punto de vista y tiempo verbal dominantes.
- Longitud típica de capítulos y escenas.
- Reglas de diálogo (atribuciones, interrupciones).
- Adjetivación (sobria, exuberante, mínima).
- Metáforas (¿se usan? ¿campo semántico?).
- Lista negra: expresiones, muletillas, tics a evitar (ejemplo real: "había trabajo que hacer", "cuatro segundos").
- Cómo se tratan los pensamientos (cursiva, sin marcar, sólo verbos declarativos).

**NO debe contener:**
- Teoría general sobre estilo.
- Reglas que no vas a cumplir.

**Uso con IA:** va en el system prompt. Es lo que evita que redacte en "voz de ChatGPT por defecto".

---

### 5.2 Raccord

**Qué es:** registro de detalles que deben mantenerse coherentes entre capítulos.

**Debe contener:**
- Objetos, heridas, ropa, coches (matrícula, color), clima, horas.
- Qué sabe cada personaje en cada punto y cómo lo supo.
- Detalles geográficos verificados (ej. "calle Belén en Castro no existe, es la Rúa").
- Datos técnicos verificados (ej. "julio es temporada alta de bonito").

**NO debe contener:**
- Todo lo que ocurre en el capítulo. Solo lo que debe persistir.
- Opiniones.

**Formato:**

```markdown
## Raccord NORTE

### Personajes
- Txema lleva gafas de montura metálica (cap 1, no de pasta).
- Nico colecciona piezas encontradas en la playa.

### Geografía (Castro)
- "rampa de San Guillén" (no "Sanguillén").
- Desde calle Escorza al puerto son 4 minutos andando.

### Temporal
- Toda la trama ocurre entre 7 y 25 de julio.
- Julio = temporada alta de bonito → barcos salen días, no horas.
```

**Uso con IA:** se actualiza **tras** cada capítulo redactado. Antes de redactar el siguiente, se revisa el raccord para detectar incoherencias pendientes.

---

### 5.3 Bitácora de decisiones

**Qué es:** registro de decisiones estructurales importantes, con fecha y razón.

**Debe contener:**
- Decisión tomada.
- Razón.
- Alternativas descartadas.
- Fecha.

**NO debe contener:**
- Diario emocional ("hoy no me salió").
- Decisiones menores.

**Ejemplo:**
> 2026-03-12 — Ferrante reescrito como ex-banquero internacional (antes: ex-seminarista). Razón: dota al personaje de acceso a redes financieras necesarias para la subtrama de cap 31. Descartado ex-seminarista por solapamiento con otros personajes eclesiásticos.

**Por qué importa:** evita reabrir debates ya cerrados seis meses después.

---

## FASE 6 — REVISIÓN

### 6.1 Plan de correcciones

**Qué es:** lista viva de problemas detectados, priorizados.

**Debe contener:**
- Problema → capítulo(s) afectado(s) → prioridad (alta/media/baja) → estado (pendiente/hecho).
- Separación entre correcciones **estructurales** (afectan a varios capítulos) y **locales** (un párrafo).

**NO debe contener:**
- Dudas sin concretar ("no sé si el cap 5 va").

---

### 6.2 Notas editoriales

**Qué es:** veredicto global tras lectura completa. Se escribe al cerrar una versión.

**Debe contener:**
- Puntuación global (si sirve para comparar versiones).
- Fortalezas concretas.
- Debilidades concretas.
- Cambios aprobados para la siguiente versión.

---

## 2. Qué NO es un documento de novela

Para cerrar el perímetro, estas cosas **no** van en los documentos de trabajo:

- Texto motivacional ("¡tú puedes!").
- Plan de marketing o portada (eso va después, en su propia carpeta).
- Apuntes emocionales del proceso.
- Ideas sueltas sin ubicación (crear un `ideas.md` separado fuera del proyecto si acaso).

---

## 3. Checklist mínima para empezar una novela nueva

Antes de escribir el cap 1, deberías tener:

- [ ] Premisa (2 frases).
- [ ] Sinopsis extendida con final incluido.
- [ ] Biblia con los 3–5 personajes principales.
- [ ] Escaleta al menos hasta el final del primer acto.
- [ ] Guía de estilo.
- [ ] Worldbuilding si aplica (imprescindible en sci-fi, recomendable en thriller técnico).
- [ ] Cronología base.

Sin esto, cualquier capítulo que escribas con IA derivará.

---

## 4. Flujo de co-escritura asistida por IA (diseño de la app)

### 4.1 Principio arquitectónico

La IA no necesita **todo** el proyecto en cada llamada. Necesita **el contexto justo**. Meter la biblia entera de 40 personajes cuando la escena tiene 2 es caro y contraproducente (la IA se distrae).

Por tanto la app es esencialmente un **ensamblador de contexto**.

### 4.2 Qué va siempre en el system prompt (contexto estable)

- Premisa.
- Tesis.
- Guía de estilo **completa**.
- Lista de personajes con una línea por cabeza (solo los principales).
- Estructura de actos.
- Reglas duras del worldbuilding (si es sci-fi).

Esto son ~1.500–3.000 tokens. Fijo en todas las llamadas.

### 4.3 Qué se recupera dinámicamente (contexto variable)

Según la tarea:

- **Redactar capítulo N:**
  - Entrada de escaleta de N, N-1, N+1.
  - Fichas completas de personajes presentes en N.
  - Entrada de raccord relevante.
  - Glosario de términos que aparecerán.
  - Texto completo del capítulo N-1 (para enganchar la prosa).
  - Resumen breve de los dos capítulos anteriores a N-1.

- **Revisar capítulo N:**
  - Texto del capítulo N.
  - Escaleta de N.
  - Fichas de personajes presentes.
  - Raccord.
  - Plan de correcciones pendientes que afectan a N.

- **Chequeo de consistencia:**
  - Texto del capítulo.
  - Raccord completo.
  - Fichas de personajes presentes.
  - Cronología.
  - Instrucción: "identifica incoherencias, no redactes".

- **Generar escena puntual dentro de capítulo:**
  - Mínimo contexto: ficha del PdV + entrada de escaleta + 500 palabras previas del propio capítulo.

### 4.4 Qué NO se mete nunca

- Capítulos muy lejanos al que se trabaja (salvo chequeo específico).
- Fichas de personajes ausentes en la escena.
- Investigación entera: solo el extracto relevante.
- Bitácora de decisiones (es para ti, no para la IA).

### 4.5 Presupuesto de tokens (orientativo, Claude con ventana larga)

- Contexto estable: 2–3k tokens.
- Contexto variable por tarea: 5–15k tokens.
- Capítulo redactado: 3–6k tokens.
- Total típico por llamada: 10–25k tokens input + 3–6k output.

Con Claude Sonnet 4 o superior esto cabe sobrado. El cuello no es la ventana, es el **coste acumulado** si redactas 40 capítulos. Conviene loggear coste por llamada.

### 4.6 Stack sugerido (Flask, tu terreno)

- **Backend:** Flask + SQLite.
- **Almacenamiento:** archivos `.md` en disco como **fuente de verdad**. SQLite solo como índice (metadatos, qué personajes salen en qué capítulo, versiones). Nunca guardes el texto en SQLite, se vuelve ingestionable.
- **Versionado:** Git. Cada capítulo es un archivo, commits por versión. No reinventes versionado.
- **Motor de plantillas de prompt:** Jinja2 con un prompt por tipo de tarea (draft, revisión, chequeo, escena).
- **Llamada API:** cliente `anthropic` oficial de Python.
- **UI mínima:** una sola página por capítulo con tres paneles: contexto ensamblado (para que veas qué le mandas), editor del capítulo, salida de la IA. Botones: Draft / Revisar / Chequear / Guardar versión.
- **Embeddings (opcional, fase 2):** si la escaleta crece mucho, embeddings para recuperar pasajes relevantes de capítulos previos. No es prioritario al principio.

### 4.7 Flujos concretos

**Flujo 1 — Redactar capítulo nuevo:**
1. Seleccionas cap N en la UI.
2. La app ensambla contexto (sección 4.3).
3. Previsualizas el contexto ensamblado.
4. Botón "Draft" → llamada a API.
5. Output en panel derecho. Editas a mano o mandas feedback.
6. Guardas versión.
7. Actualizas raccord manualmente (o con una llamada separada "extrae raccord de este capítulo").

**Flujo 2 — Chequeo de consistencia (muy útil en trilogías):**
1. Seleccionas cap o rango.
2. Contexto: texto + raccord + cronología + fichas.
3. Prompt: "actúa como editor de consistencia, devuelve lista de incoherencias numeradas. No reescribas".
4. Revisas, actualizas plan de correcciones.

**Flujo 3 — Reescritura dirigida:**
1. Seleccionas un pasaje.
2. Describes el cambio ("añade temblor en la mano de Martín antes de cortar la muestra").
3. Contexto mínimo: pasaje + ficha del personaje + estilo.
4. Output: solo el pasaje reescrito, no el capítulo entero.

### 4.8 Riesgos reales

- **Deriva de voz.** Tras 20 capítulos redactados con IA el estilo se homogeniza. Contrapeso: leer cada capítulo en voz alta y re-editar a mano los pasajes donde notes "voz de asistente".
- **Dependencia del contexto ensamblado.** Si el raccord está desactualizado, la IA propagará el error. Disciplina: actualizar raccord tras cada capítulo.
- **Coste acumulado.** En una novela de 40 capítulos con varias iteraciones por capítulo, puedes irte a cientos de euros. Ponle un contador visible.
- **Tentación de aceptar output sin editar.** La IA escribe "correcto", no "tuyo". El valor editorial lo sigues poniendo tú.

---

## 5. Cómo encaja con tus proyectos actuales

- **Chari** y **Lote 7** están en fase de concepción: necesitan pasar por **toda la Fase 1 y 2** antes de tocar capítulos. Empieza por ahí.
- **NORTE** está en Fase 6 (revisión). Los documentos ya existen; lo que falta es disciplina en el plan de correcciones.
- **Alianza** y **La cadena del silencio** están en un estado mixto: documentos maduros, correcciones pendientes de ejecución.

La app tendría sentido como pieza que unifica todos estos proyectos en una misma estructura, no un tooling ad-hoc por novela.

---

## 6. Lo mínimo imprescindible si hoy empiezas de cero

Si tuvieras que escribir **una sola cosa** antes de teclear el capítulo 1: la **sinopsis extendida con el final incluido**. Todo lo demás se puede iterar sobre la marcha; la sinopsis no.
