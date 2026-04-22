(() => {
  "use strict";

  const state = {
    proyectoSlug: null,
    arbol: null,
    rutaActiva: null,
    contenidoCargado: "",
    dirty: false,
    editor: null,
    conversacionId: null,
    costeAcumulado: 0,
    guardando: false,
    saveTimer: null,
  };

  // --------------------------------------------------------------------- API
  function slugURL(slug) {
    return encodeURIComponent((slug || "").replace(/\//g, "::"));
  }

  async function api(url, opts = {}) {
    const res = await fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (res.status === 401) {
      window.location.href = "/login";
      throw new Error("unauthenticated");
    }
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`${res.status} ${res.statusText}: ${text}`);
    }
    return res.json();
  }

  // --------------------------------------------------------------- Proyectos
  async function cargarProyectos() {
    const data = await api("/api/proyectos");
    const select = document.getElementById("proyecto-select");
    select.innerHTML = "";
    const opts = [];
    for (const p of data.independientes || []) {
      opts.push({ value: p.slug, label: p.nombre });
    }
    for (const s of data.sagas || []) {
      for (const libro of s.libros || []) {
        opts.push({
          value: `${s.slug}/${libro.slug}`,
          label: `${s.nombre} — ${libro.titulo}`,
          sagaSlug: s.slug,
        });
      }
      if (!(s.libros || []).length) {
        opts.push({ value: `__saga__/${s.slug}`, label: `${s.nombre} (sin libros)`, disabled: true, sagaSlug: s.slug });
      }
    }
    if (!opts.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(ningún proyecto)";
      select.appendChild(opt);
      select.disabled = true;
      mostrarEstadoVacio();
      return;
    }
    for (const o of opts) {
      const el = document.createElement("option");
      el.value = o.value;
      el.textContent = o.label;
      if (o.disabled) el.disabled = true;
      if (o.sagaSlug) el.dataset.sagaSlug = o.sagaSlug;
      select.appendChild(el);
    }
    select.disabled = false;
    const primero = opts.find((o) => !o.disabled) || opts[0];
    select.value = primero.value;
    await seleccionarProyecto(primero.value);
  }

  async function seleccionarProyecto(slug) {
    if (slug && slug.startsWith("__saga__/")) {
      // Saga sin libros: no es seleccionable como proyecto; sólo actualiza botón libro.
      const sagaSlug = slug.slice("__saga__/".length);
      state.proyectoSlug = null;
      state.sagaActiva = sagaSlug;
      actualizarBotonNuevoLibro();
      document.getElementById("arbol-contenido").innerHTML =
        '<div class="empty-state">Saga sin libros. Usa "+ Libro" para añadir el primero.</div>';
      return;
    }
    state.proyectoSlug = slug;
    state.rutaActiva = null;
    state.contenidoCargado = "";
    state.dirty = false;
    state.conversacionId = null;
    state.costeAcumulado = 0;
    state.sagaActiva = slug && slug.includes("/") ? slug.split("/")[0] : null;
    actualizarCoste();
    actualizarBotonNuevoLibro();
    await Promise.all([cargarArbol(), cargarGitStatus()]);
    document.getElementById("workspace-titulo").textContent = "— selecciona un fichero —";
    if (state.editor) state.editor.value("");
    document.getElementById("chat-mensajes").innerHTML = "";
  }

  function actualizarBotonNuevoLibro() {
    const btn = document.getElementById("btn-nuevo-libro");
    if (!btn) return;
    btn.style.display = state.sagaActiva ? "" : "none";
    if (state.sagaActiva) btn.title = `Añadir libro a la saga ${state.sagaActiva}`;
  }

  function mostrarEstadoVacio() {
    document.getElementById("arbol-contenido").innerHTML =
      '<div class="empty-state">No hay proyectos.<br>Crea uno con <code>python manage.py new_project &lt;slug&gt;</code>.</div>';
    document.getElementById("workspace-titulo").textContent = "";
  }

  // ------------------------------------------------------------------ Árbol
  async function cargarArbol() {
    if (!state.proyectoSlug) return;
    const data = await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/arbol`);
    state.arbol = data;
    renderizarArbol();
  }

  function renderizarArbol() {
    const cont = document.getElementById("arbol-contenido");
    cont.innerHTML = "";
    for (const carpeta of state.arbol.carpetas || []) {
      const div = document.createElement("div");
      div.className = "arbol-carpeta";
      const h = document.createElement("h3");
      const spanTitulo = document.createElement("span");
      spanTitulo.textContent = carpeta.titulo_humano;
      h.appendChild(spanTitulo);
      const btnAdd = document.createElement("button");
      btnAdd.className = "btn-add-fichero";
      btnAdd.type = "button";
      btnAdd.title = `Crear en ${carpeta.titulo_humano}`;
      btnAdd.textContent = "+";
      btnAdd.addEventListener("click", (ev) => {
        ev.stopPropagation();
        abrirModalNuevoFichero(carpeta.nombre);
      });
      h.appendChild(btnAdd);
      div.appendChild(h);
      for (const f of carpeta.ficheros) {
        const a = document.createElement("a");
        a.className = "arbol-fichero";
        if (state.rutaActiva === f.ruta) a.classList.add("activo");
        a.href = "#";
        if (f.etiqueta_ui) {
          const et = document.createElement("span");
          et.className = "etiqueta";
          et.textContent = f.etiqueta_ui;
          a.appendChild(et);
        }
        a.appendChild(document.createTextNode(f.titulo || f.slug));
        a.addEventListener("click", (e) => {
          e.preventDefault();
          abrirFichero(f.ruta);
        });
        a.addEventListener("contextmenu", (e) => {
          e.preventDefault();
          mostrarMenuContextual(e.clientX, e.clientY, [
            { texto: "Abrir", accion: () => abrirFichero(f.ruta) },
            { texto: "Mejorar con IA (propaga al canon)", accion: () => accionMejorarConIA(f.ruta) },
            { texto: "Ver historial", accion: () => accionVerHistorial(f.ruta) },
            { texto: "Renombrar", accion: () => accionRenombrar(f.ruta) },
            { texto: "Borrar", peligro: true, accion: () => accionBorrar(f.ruta) },
          ]);
        });
        enganchaDragDrop(a, f, carpeta.nombre);
        div.appendChild(a);
      }
      cont.appendChild(div);
    }
  }

  // ----------------------------------------------------------------- Editor
  function inicializarEditor() {
    const textarea = document.getElementById("editor");
    const EasyMDEClass = window.EasyMDE;
    if (!EasyMDEClass) {
      console.warn("EasyMDE no cargado todavía, reintentando...");
      setTimeout(inicializarEditor, 100);
      return;
    }
    state.editor = new EasyMDEClass({
      element: textarea,
      autoDownloadFontAwesome: false,
      spellChecker: false,
      status: ["lines", "words"],
      toolbar: [
        "bold", "italic", "heading", "|",
        "quote", "unordered-list", "ordered-list", "|",
        "link", "preview", "side-by-side", "|",
        "guide",
      ],
      minHeight: "200px",
      autosave: { enabled: false },
      placeholder: "Selecciona un fichero del árbol para empezar a editar.",
    });
    state.editor.codemirror.on("change", () => {
      if (state.rutaActiva == null) return;
      const val = state.editor.value();
      const previoDirty = state.dirty;
      state.dirty = val !== state.contenidoCargado;
      if (state.dirty !== previoDirty) actualizarEstadoGuardado();
      actualizarContadorPalabras(val);
      programarAutoSave();
    });
  }

  function actualizarContadorPalabras(texto) {
    const el = document.getElementById("workspace-contador");
    if (!el) return;
    const cuerpo = quitarFrontmatter(texto);
    const palabras = (cuerpo.match(/\b[\p{L}\p{N}'’-]+\b/gu) || []).length;
    el.textContent = `${palabras} palabras`;
  }

  function quitarFrontmatter(s) {
    if (!s.startsWith("---")) return s;
    const fin = s.indexOf("\n---", 3);
    if (fin < 0) return s;
    return s.slice(fin + 4).replace(/^\n/, "");
  }

  async function abrirFichero(ruta) {
    if (state.dirty) {
      const ok = confirm("Hay cambios sin guardar. ¿Descartar y abrir otro fichero?");
      if (!ok) return;
    }
    const data = await api(
      `/api/proyecto/${slugURL(state.proyectoSlug)}/fichero?ruta=${encodeURIComponent(ruta)}`
    );
    state.rutaActiva = ruta;
    // Pintamos el fichero con frontmatter reconstruido si hay metadata.
    const contenidoVisible = reconstruirConFrontmatter(data.metadata, data.content);
    state.contenidoCargado = contenidoVisible;
    state.dirty = false;
    state.editor.value(contenidoVisible);
    document.getElementById("workspace-titulo").textContent = data.title || ruta;
    renderizarArbol();
    actualizarEstadoGuardado();
  }

  function reconstruirConFrontmatter(metadata, content) {
    if (!metadata || Object.keys(metadata).length === 0) return content;
    const lineas = ["---"];
    for (const [k, v] of Object.entries(metadata)) {
      lineas.push(`${k}: ${serializarYamlValor(v)}`);
    }
    lineas.push("---", "");
    return lineas.join("\n") + content;
  }

  function serializarYamlValor(v) {
    if (Array.isArray(v)) {
      return "[" + v.map((x) => String(x)).join(", ") + "]";
    }
    if (v == null) return "";
    return String(v);
  }

  function programarAutoSave() {
    if (state.saveTimer) clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(() => {
      if (state.dirty && state.rutaActiva) guardarFichero();
    }, 2000);
  }

  async function guardarFichero() {
    if (state.guardando) return;
    state.guardando = true;
    document.getElementById("workspace-estado").textContent = "guardando…";
    document.getElementById("workspace-estado").className = "estado-guardado guardando";
    try {
      const contenido = state.editor.value();
      await api(
        `/api/proyecto/${slugURL(state.proyectoSlug)}/fichero`,
        {
          method: "PUT",
          body: JSON.stringify({
            ruta: state.rutaActiva,
            content: contenido,
            commit_message: "Edición manual",
          }),
        }
      );
      state.contenidoCargado = contenido;
      state.dirty = false;
      await cargarGitStatus();
      document.getElementById("workspace-estado").textContent = "guardado";
      document.getElementById("workspace-estado").className = "estado-guardado guardado";
    } catch (e) {
      console.error(e);
      document.getElementById("workspace-estado").textContent = "error al guardar";
      document.getElementById("workspace-estado").className = "estado-guardado error";
    } finally {
      state.guardando = false;
    }
  }

  function actualizarEstadoGuardado() {
    const el = document.getElementById("workspace-estado");
    if (!state.rutaActiva) { el.textContent = ""; el.className = "estado-guardado"; return; }
    if (state.dirty) { el.textContent = "modificado"; el.className = "estado-guardado dirty"; return; }
    el.textContent = "guardado";
    el.className = "estado-guardado guardado";
  }

  // ----------------------------------------------------------------- Git
  async function cargarGitStatus() {
    if (!state.proyectoSlug) return;
    try {
      const g = await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/git_status`);
      const dot = document.getElementById("git-indicator");
      const label = document.getElementById("git-label");
      dot.className = "sync-dot";
      if (g.estado === "sincronizado") {
        dot.classList.add("sync-ok");
        label.textContent = g.ultimo_commit ? `sync · ${g.ultimo_commit}` : "sync";
      } else if (g.estado === "pendiente") {
        dot.classList.add("sync-pendiente");
        label.textContent = `pendiente (${g.commits_pendientes})`;
      } else {
        dot.classList.add("sync-error");
        label.textContent = "error";
      }
    } catch (e) { /* silencioso */ }
  }

  // ----------------------------------------------------------------- Chat
  function montarChat() {
    const form = document.getElementById("chat-form");
    const input = document.getElementById("chat-input");
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      enviarMensajeChat();
    });
    input.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        enviarMensajeChat();
      }
    });
  }

  async function enviarMensajeChat() {
    const input = document.getElementById("chat-input");
    const mensaje = input.value.trim();
    if (!mensaje || !state.proyectoSlug) return;
    const boton = document.getElementById("chat-enviar");
    boton.disabled = true;

    pintarMensajeChat("user", mensaje);
    pintarMensajeChat("sistema", "IA pensando…", "pensando");
    input.value = "";

    try {
      const modeloSel = document.getElementById("modelo-select");
      const modelo = modeloSel ? modeloSel.value : "";
      const body = {
        mensaje,
        ruta_activa: state.rutaActiva,
        conversacion_id: state.conversacionId,
      };
      if (modelo) body.modelo = modelo;
      const resp = await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/chat`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      quitarMensajePensando();
      state.conversacionId = resp.conversacion_id;
      state.costeAcumulado += resp.coste_eur || 0;
      actualizarCoste();
      pintarMensajeChat("assistant", resp.respuesta || "", null, resp.tool_calls);
      if (resp.propuestas && resp.propuestas.length) {
        pintarPropuestas(resp.propuestas);
      }
      if (resp.truncado_por_limite) {
        pintarMensajeChat("sistema", "Turno truncado por límite de herramientas.");
      }
    } catch (e) {
      quitarMensajePensando();
      pintarMensajeChat("error", String(e.message || e));
    } finally {
      boton.disabled = false;
      input.focus();
    }
  }

  function pintarMensajeChat(rol, texto, marker, toolCalls) {
    const cont = document.getElementById("chat-mensajes");
    const div = document.createElement("div");
    div.className = "chat-mensaje " + rol;
    if (marker) div.dataset.marker = marker;
    div.textContent = texto;
    if (toolCalls && toolCalls.length) {
      const tc = document.createElement("div");
      tc.className = "tool-calls";
      for (const t of toolCalls) {
        const line = document.createElement("div");
        line.className = "tool-call" + (t.is_error ? " error" : "");
        const args = Object.entries(t.input || {})
          .map(([k, v]) => `${k}=${abbr(String(v))}`)
          .join(", ");
        line.textContent = `▸ ${t.name}(${args})`;
        tc.appendChild(line);
      }
      div.appendChild(tc);
    }
    cont.appendChild(div);
    cont.scrollTop = cont.scrollHeight;
  }

  function pintarPropuestas(propuestas) {
    const cont = document.getElementById("chat-mensajes");
    const wrap = document.createElement("div");
    wrap.className = "propuestas-bloque";

    const header = document.createElement("div");
    header.className = "propuestas-header";
    const titulo = document.createElement("span");
    titulo.textContent = `${propuestas.length} propuesta${propuestas.length === 1 ? "" : "s"} pendiente${propuestas.length === 1 ? "" : "s"}`;
    header.appendChild(titulo);
    if (propuestas.length > 1) {
      const btnAll = document.createElement("button");
      btnAll.className = "btn-mini btn-aplicar";
      btnAll.textContent = "Aplicar todas";
      btnAll.addEventListener("click", () => aplicarTodas(propuestas, wrap));
      const btnNone = document.createElement("button");
      btnNone.className = "btn-mini btn-rechazar";
      btnNone.textContent = "Rechazar todas";
      btnNone.addEventListener("click", () => rechazarTodas(propuestas, wrap));
      const acciones = document.createElement("span");
      acciones.className = "propuestas-bulk";
      acciones.append(btnAll, btnNone);
      header.appendChild(acciones);
    }
    wrap.appendChild(header);

    for (const p of propuestas) {
      wrap.appendChild(renderizarPropuesta(p, wrap));
    }
    cont.appendChild(wrap);
    cont.scrollTop = cont.scrollHeight;
  }

  function renderizarPropuesta(p, contenedorPadre) {
    const card = document.createElement("div");
    card.className = "propuesta";
    card.dataset.propuestaId = p.id;

    const cabecera = document.createElement("div");
    cabecera.className = "propuesta-cabecera";
    const titulo = document.createElement("strong");
    titulo.textContent = tituloPropuesta(p);
    cabecera.appendChild(titulo);
    const motivo = document.createElement("div");
    motivo.className = "propuesta-motivo";
    motivo.textContent = p.motivo;
    cabecera.appendChild(motivo);
    card.appendChild(cabecera);

    if (p.diff) {
      const pre = document.createElement("pre");
      pre.className = "diff";
      pre.appendChild(renderizarDiff(p.diff));
      card.appendChild(pre);
    } else if (p.tipo === "reordenar_capitulos") {
      const info = document.createElement("div");
      info.className = "propuesta-info";
      info.textContent = `Nuevo orden: ${(p.nuevo_orden || []).join(" → ")}`;
      card.appendChild(info);
    } else if (p.tipo === "actualizar_grafo_relaciones") {
      const ul = document.createElement("ul");
      ul.className = "propuesta-info";
      for (const c of p.cambios || []) {
        const li = document.createElement("li");
        li.textContent = `[${c.accion}] ${c.seccion}: ${c.texto}`;
        ul.appendChild(li);
      }
      card.appendChild(ul);
    }

    const acciones = document.createElement("div");
    acciones.className = "propuesta-acciones";
    const btnOk = document.createElement("button");
    btnOk.className = "btn-mini btn-aplicar";
    btnOk.textContent = "Aplicar";
    btnOk.addEventListener("click", () => aplicarPropuesta(p.id, card));
    const btnEdit = document.createElement("button");
    btnEdit.className = "btn-mini btn-editar";
    btnEdit.textContent = "Editar";
    if (p.tipo !== "modificar_fichero" && p.tipo !== "crear_fichero") btnEdit.disabled = true;
    btnEdit.addEventListener("click", () => editarPropuesta(p, card));
    const btnNo = document.createElement("button");
    btnNo.className = "btn-mini btn-rechazar";
    btnNo.textContent = "Rechazar";
    btnNo.addEventListener("click", () => rechazarPropuesta(p.id, card));
    acciones.append(btnOk, btnEdit, btnNo);
    card.appendChild(acciones);

    return card;
  }

  function editarPropuesta(p, card) {
    if (card.querySelector(".propuesta-edit")) return;
    const edit = document.createElement("div");
    edit.className = "propuesta-edit";
    const ta = document.createElement("textarea");
    ta.value = p.contenido_nuevo || "";
    const btnOk = document.createElement("button");
    btnOk.className = "btn-mini btn-aplicar";
    btnOk.textContent = "Guardar cambios";
    const btnCancel = document.createElement("button");
    btnCancel.className = "btn-mini btn-rechazar";
    btnCancel.textContent = "Cancelar edición";
    const barra = document.createElement("div");
    barra.className = "propuesta-acciones";
    barra.append(btnOk, btnCancel);
    edit.append(ta, barra);
    card.appendChild(edit);

    btnCancel.addEventListener("click", () => edit.remove());
    btnOk.addEventListener("click", async () => {
      try {
        const resp = await api(
          `/api/proyecto/${slugURL(state.proyectoSlug)}/propuesta/${p.id}`,
          { method: "PUT", body: JSON.stringify({ contenido_nuevo: ta.value }) }
        );
        p.contenido_nuevo = ta.value;
        p.diff = resp.propuesta.diff;
        // Repintar el diff existente.
        const pre = card.querySelector(".diff");
        if (pre) {
          pre.innerHTML = "";
          pre.appendChild(renderizarDiff(p.diff));
        }
        edit.remove();
      } catch (e) {
        alert("Error editando: " + (e.message || e));
      }
    });
  }

  function tituloPropuesta(p) {
    if (p.tipo === "modificar_fichero") return `Modificar ${p.ruta}`;
    if (p.tipo === "crear_fichero") return `Crear ${p.ruta}`;
    if (p.tipo === "reordenar_capitulos") return "Reordenar capítulos";
    if (p.tipo === "actualizar_grafo_relaciones") return "Actualizar grafo de relaciones";
    return p.tipo;
  }

  function renderizarDiff(diffText) {
    const frag = document.createDocumentFragment();
    for (const linea of diffText.split("\n")) {
      const span = document.createElement("span");
      if (linea.startsWith("+++") || linea.startsWith("---") || linea.startsWith("@@")) {
        span.className = "diff-meta";
      } else if (linea.startsWith("+")) {
        span.className = "diff-add";
      } else if (linea.startsWith("-")) {
        span.className = "diff-del";
      } else {
        span.className = "diff-ctx";
      }
      span.textContent = linea + "\n";
      frag.appendChild(span);
    }
    return frag;
  }

  async function aplicarPropuesta(id, card) {
    marcarCardEstado(card, "aplicando…");
    try {
      await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/propuesta/${id}/aplicar`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      marcarCardEstado(card, "aplicada", "ok");
      desactivarBotones(card);
      await Promise.all([cargarArbol(), cargarGitStatus()]);
      if (state.rutaActiva) await refrescarFicheroActivo();
    } catch (e) {
      marcarCardEstado(card, "error al aplicar", "err");
      console.error(e);
    }
  }

  async function rechazarPropuesta(id, card) {
    try {
      await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/propuesta/${id}/rechazar`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      marcarCardEstado(card, "rechazada", "rechazada");
      desactivarBotones(card);
    } catch (e) {
      marcarCardEstado(card, "error al rechazar", "err");
      console.error(e);
    }
  }

  async function aplicarTodas(propuestas, wrap) {
    for (const p of propuestas) {
      const card = wrap.querySelector(`[data-propuesta-id="${p.id}"]`);
      if (card && !card.dataset.resuelta) await aplicarPropuesta(p.id, card);
    }
  }

  async function rechazarTodas(propuestas, wrap) {
    for (const p of propuestas) {
      const card = wrap.querySelector(`[data-propuesta-id="${p.id}"]`);
      if (card && !card.dataset.resuelta) await rechazarPropuesta(p.id, card);
    }
  }

  function marcarCardEstado(card, texto, clase) {
    let banner = card.querySelector(".propuesta-banner");
    if (!banner) {
      banner = document.createElement("div");
      banner.className = "propuesta-banner";
      card.appendChild(banner);
    }
    banner.textContent = texto;
    banner.dataset.estado = clase || "";
  }

  function desactivarBotones(card) {
    card.dataset.resuelta = "1";
    for (const b of card.querySelectorAll("button")) b.disabled = true;
  }

  async function refrescarFicheroActivo() {
    try {
      const data = await api(
        `/api/proyecto/${slugURL(state.proyectoSlug)}/fichero?ruta=${encodeURIComponent(state.rutaActiva)}`
      );
      const contenidoVisible = reconstruirConFrontmatter(data.metadata, data.content);
      state.contenidoCargado = contenidoVisible;
      state.dirty = false;
      state.editor.value(contenidoVisible);
      actualizarEstadoGuardado();
    } catch (e) { /* ignorar */ }
  }

  function quitarMensajePensando() {
    const cont = document.getElementById("chat-mensajes");
    for (const child of Array.from(cont.children)) {
      if (child.dataset && child.dataset.marker === "pensando") cont.removeChild(child);
    }
  }

  function abbr(s) { return s.length > 40 ? s.slice(0, 37) + "…" : s; }

  function actualizarCoste() {
    document.getElementById("chat-coste").textContent =
      state.costeAcumulado.toFixed(4).replace(/0+$/, "").replace(/\.$/, "") + " €";
  }

  // ----------------------------------------------------------- Modales
  function mostrarModal(titulo, campos, onConfirmar) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    const modal = document.createElement("div");
    modal.className = "modal";
    const h = document.createElement("h2");
    h.textContent = titulo;
    modal.appendChild(h);

    const inputs = {};
    for (const c of campos) {
      const label = document.createElement("label");
      const span = document.createElement("span");
      span.textContent = c.label;
      label.appendChild(span);
      let input;
      if (c.type === "textarea") {
        input = document.createElement("textarea");
      } else if (c.type === "select") {
        input = document.createElement("select");
        for (const opt of c.options) {
          const o = document.createElement("option");
          o.value = opt.value;
          o.textContent = opt.label;
          input.appendChild(o);
        }
      } else {
        input = document.createElement("input");
        input.type = c.type || "text";
      }
      input.value = c.default || "";
      if (c.placeholder) input.placeholder = c.placeholder;
      if (c.pattern) input.pattern = c.pattern;
      label.appendChild(input);
      if (c.ayuda) {
        const a = document.createElement("div");
        a.className = "modal-ayuda";
        a.textContent = c.ayuda;
        label.appendChild(a);
      }
      modal.appendChild(label);
      inputs[c.name] = input;
    }

    const errorDiv = document.createElement("div");
    errorDiv.className = "modal-error";
    modal.appendChild(errorDiv);

    const acciones = document.createElement("div");
    acciones.className = "modal-acciones";
    const btnCancel = document.createElement("button");
    btnCancel.className = "btn-cancelar";
    btnCancel.textContent = "Cancelar";
    const btnOk = document.createElement("button");
    btnOk.className = "btn-confirmar";
    btnOk.textContent = "Crear";
    acciones.append(btnCancel, btnOk);
    modal.appendChild(acciones);

    const cerrar = () => backdrop.remove();
    btnCancel.addEventListener("click", cerrar);
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) cerrar(); });
    btnOk.addEventListener("click", async () => {
      errorDiv.textContent = "";
      const valores = {};
      for (const [k, input] of Object.entries(inputs)) valores[k] = input.value;
      btnOk.disabled = true;
      try {
        await onConfirmar(valores);
        cerrar();
      } catch (e) {
        errorDiv.textContent = (e && e.message) ? e.message : String(e);
        btnOk.disabled = false;
      }
    });

    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    const primero = modal.querySelector("input, textarea, select");
    if (primero) primero.focus();
  }

  function slugify(s) {
    return (s || "")
      .toLowerCase()
      .normalize("NFD").replace(/[̀-ͯ]/g, "")
      .replace(/ñ/g, "n").replace(/Ñ/g, "n")
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
  }

  function abrirModalRemoto() {
    if (!state.proyectoSlug) return alert("Selecciona un proyecto.");
    mostrarModal(
      "Configurar Git remoto",
      [
        { name: "url", label: "URL del remoto", placeholder: "git@github.com:usuario/repo.git",
          ayuda: "Usa SSH (ssh-agent debe tener la clave cargada) o HTTPS con credentials helper." },
        { name: "auto_push", label: "Auto-push tras cada commit", type: "select",
          options: [{value: "true", label: "Sí"}, {value: "false", label: "No"}], default: "true" },
      ],
      async (v) => {
        const url = (v.url || "").trim();
        if (!url) throw new Error("URL vacía.");
        await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/git/remoto`, {
          method: "POST",
          body: JSON.stringify({ url, auto_push: v.auto_push !== "false" }),
        });
        await cargarGitStatus();
      }
    );
  }

  function abrirModalNuevaSaga() {
    mostrarModal(
      "Nueva saga",
      [
        { name: "nombre", label: "Nombre", placeholder: "Mi saga" },
        { name: "slug", label: "Slug", pattern: "[a-z0-9_]+", ayuda: "ASCII minúsculas, dígitos y '_'." },
      ],
      async (v) => {
        const slug = slugify(v.slug || v.nombre);
        if (!slug) throw new Error("Slug vacío.");
        const resp = await fetch("/api/sagas", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slug, nombre: v.nombre || slug }),
        });
        if (!resp.ok) throw new Error(await resp.text());
        await cargarProyectos();
      }
    );
  }

  function abrirModalNuevoLibro() {
    if (!state.sagaActiva) { alert("Selecciona primero una saga."); return; }
    mostrarModal(
      `Nuevo libro en saga ${state.sagaActiva}`,
      [
        { name: "nombre", label: "Título del libro" },
        { name: "slug", label: "Slug", pattern: "[a-z0-9_]+" },
        { name: "orden", label: "Orden en la saga", type: "number", default: "1" },
      ],
      async (v) => {
        const slug = slugify(v.slug || v.nombre);
        if (!slug) throw new Error("Slug vacío.");
        const orden = parseInt(v.orden || "1", 10) || 1;
        const resp = await fetch(`/api/saga/${encodeURIComponent(state.sagaActiva)}/libros`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slug, nombre: v.nombre || slug, orden }),
        });
        if (!resp.ok) throw new Error(await resp.text());
        const data = await resp.json();
        await cargarProyectos();
        document.getElementById("proyecto-select").value = data.slug;
        await seleccionarProyecto(data.slug);
      }
    );
  }

  function abrirModalNuevaNovela() {
    mostrarModal(
      "Nueva novela",
      [
        { name: "nombre", label: "Nombre", placeholder: "Mi novela", ayuda: "Título humano. Puedes cambiarlo después." },
        { name: "slug", label: "Slug", placeholder: "mi_novela", pattern: "[a-z0-9_]+", ayuda: "ASCII minúsculas, dígitos y '_'. No cambia durante la vida del proyecto." },
      ],
      async (v) => {
        const slug = slugify(v.slug || v.nombre);
        if (!slug) throw new Error("Slug vacío.");
        const resp = await fetch("/api/proyectos", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slug, nombre: v.nombre || slug }),
        });
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(text || `Error ${resp.status}`);
        }
        await cargarProyectos();
        const select = document.getElementById("proyecto-select");
        select.value = slug;
        await seleccionarProyecto(slug);
      }
    );
  }

  function plantillaPorCarpeta(carpeta, slug) {
    const titulo = slug.split("_").map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
    if (carpeta === "04_capitulos") {
      return {
        metadata: `---\nslug: ${slug}\npersonajes: []\npov: \nestado: esqueleto\n---\n\n`,
        cuerpo: `# ${titulo}\n\n`,
      };
    }
    if (carpeta === "01_personajes") {
      return {
        metadata: `---\nslug: ${slug}\ntipo: personaje\naparece_en: []\nrol: secundario\n---\n\n`,
        cuerpo: `# ${titulo}\n\n## Identidad\n- Edad: \n- Profesión: \n\n## Rasgos físicos permanentes\n- \n\n## Arco\n- \n\n## Voz\n- \n`,
      };
    }
    if (carpeta === "02_mundo") {
      return {
        metadata: `---\nslug: ${slug}\ntipo: lugar\naparece_en: []\n---\n\n`,
        cuerpo: `# ${titulo}\n\n## Descripción física\n- \n\n## Historia\n- \n\n## Relevancia narrativa\n- \n`,
      };
    }
    return { metadata: "", cuerpo: `# ${titulo}\n\n` };
  }

  function abrirModalNuevoFichero(carpeta) {
    const titulo = `Nuevo en ${carpeta}`;
    mostrarModal(
      titulo,
      [
        { name: "slug", label: "Slug", placeholder: "ej. primera_noche", pattern: "[a-z0-9_]+", ayuda: "ASCII minúsculas, dígitos y '_'. Estable." },
      ],
      async (v) => {
        const slug = slugify(v.slug);
        if (!slug) throw new Error("Slug vacío.");
        const plantilla = plantillaPorCarpeta(carpeta, slug);
        const contenido = plantilla.metadata + plantilla.cuerpo;
        const ruta = `${carpeta}/${slug}.md`;
        const resp = await fetch(`/api/proyecto/${slugURL(state.proyectoSlug)}/fichero`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ruta,
            content: contenido,
            commit_message: `Creado ${slug}`,
          }),
        });
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(text || `Error ${resp.status}`);
        }
        await Promise.all([cargarArbol(), cargarGitStatus()]);
        await abrirFichero(ruta);
      }
    );
  }

  // ----------------------------------------------------------------- Modos del workspace
  function montarModos() {
    for (const btn of document.querySelectorAll(".btn-modo")) {
      btn.addEventListener("click", () => cambiarModo(btn.dataset.modo));
    }
  }

  function cambiarModo(modo) {
    for (const btn of document.querySelectorAll(".btn-modo")) {
      btn.classList.toggle("activo", btn.dataset.modo === modo);
    }
    for (const panel of document.querySelectorAll(".modo-panel")) {
      panel.classList.toggle("activo", panel.id === `modo-${modo}`);
    }
    if (modo === "historial") cargarModoHistorial();
    if (modo === "audit") cargarModoAudit();
    if (modo === "auditoria") cargarModoAuditoria();
  }

  // ----------------------------------------------------------- Modo historial
  async function cargarModoHistorial() {
    const cont = document.getElementById("modo-historial");
    if (!state.proyectoSlug || !state.rutaActiva) {
      cont.innerHTML = '<div class="empty-state">Abre un fichero para ver su historial.</div>';
      return;
    }
    cont.innerHTML = '<div class="empty-state">Cargando historial…</div>';
    try {
      const data = await api(
        `/api/proyecto/${slugURL(state.proyectoSlug)}/fichero/historial?ruta=${encodeURIComponent(state.rutaActiva)}`
      );
      renderizarHistorial(cont, data.versiones || []);
    } catch (e) {
      cont.innerHTML = `<div class="empty-state">Error: ${e.message || e}</div>`;
    }
  }

  function renderizarHistorial(cont, versiones) {
    cont.innerHTML = "";
    const lista = document.createElement("div");
    lista.className = "historial-lista";
    const preview = document.createElement("pre");
    preview.className = "historial-preview";
    preview.textContent = "Selecciona una versión para ver su contenido.";
    const acciones = document.createElement("div");
    acciones.className = "historial-acciones";
    const btnRestaurar = document.createElement("button");
    btnRestaurar.className = "btn-mini btn-aplicar";
    btnRestaurar.textContent = "Restaurar esta versión";
    btnRestaurar.disabled = true;
    acciones.appendChild(btnRestaurar);

    let activa = null;

    for (const v of versiones) {
      const div = document.createElement("div");
      div.className = "historial-entrada";
      div.innerHTML =
        `<div><span class="historial-autor">${v.autor}</span><span class="historial-motivo">${escape(v.motivo || "")}</span></div>` +
        `<div class="historial-meta">${v.commit} · ${v.fecha}</div>`;
      div.addEventListener("click", async () => {
        if (activa) activa.classList.remove("activa");
        div.classList.add("activa");
        activa = div;
        btnRestaurar.disabled = true;
        preview.textContent = "Cargando…";
        try {
          const vd = await api(
            `/api/proyecto/${slugURL(state.proyectoSlug)}/fichero/version?ruta=${encodeURIComponent(state.rutaActiva)}&commit=${encodeURIComponent(v.commit)}`
          );
          preview.textContent = vd.content || "";
          btnRestaurar.disabled = false;
          btnRestaurar.onclick = () => restaurarVersion(v.commit);
        } catch (e) {
          preview.textContent = `Error: ${e.message || e}`;
        }
      });
      lista.appendChild(div);
    }

    if (!versiones.length) {
      lista.innerHTML = '<div class="empty-state">Sin versiones previas.</div>';
    }

    cont.append(lista, preview, acciones);
  }

  async function restaurarVersion(commit) {
    if (!confirm(`Restaurar ${state.rutaActiva} a ${commit}?`)) return;
    try {
      await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/fichero/restaurar`, {
        method: "POST",
        body: JSON.stringify({ ruta: state.rutaActiva, commit }),
      });
      await Promise.all([cargarArbol(), cargarGitStatus()]);
      await refrescarFicheroActivo();
      cambiarModo("editor");
    } catch (e) {
      alert("Error restaurando: " + (e.message || e));
    }
  }

  function escape(s) {
    return String(s || "").replace(/[&<>"]/g, (c) => (
      {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]
    ));
  }

  // -------------------------------------------------------- Modo auditoría
  const AUDITORIA_CATEGORIAS = [
    { key: "repeticiones_palabra", label: "Repeticiones palabra" },
    { key: "repeticiones_ngrama", label: "Repeticiones frase" },
    { key: "tics", label: "Tics / muletillas" },
    { key: "dicendi", label: "Verbos dicendi" },
    { key: "tiempos", label: "Tiempos verbales" },
    { key: "erratas", label: "Erratas tipográficas" },
    { key: "longitud", label: "Longitud" },
    { key: "cronologia", label: "Cronología" },
    { key: "coherencia", label: "Coherencia canon" },
  ];

  async function cargarModoAuditoria() {
    const cont = document.getElementById("modo-auditoria");
    if (!state.proyectoSlug) {
      cont.innerHTML = '<div class="empty-state">Selecciona un proyecto.</div>';
      return;
    }
    if (!cont.dataset.montado) {
      cont.innerHTML = `
        <div class="auditoria-controles">
          <label>Ámbito:
            <select id="auditoria-ambito">
              <option value="actual">Capítulo activo</option>
              <option value="proyecto">Todo el proyecto</option>
            </select>
          </label>
          <label>Min palabras:
            <input type="number" id="auditoria-min" value="1500" style="width:70px" />
          </label>
          <label>Max palabras:
            <input type="number" id="auditoria-max" value="2500" style="width:70px" />
          </label>
          <button type="button" id="auditoria-ejecutar" class="auditoria-boton">Ejecutar auditoría</button>
          <button type="button" id="auditoria-ia" class="auditoria-boton" style="background:var(--warn);color:#0c1014" title="Lanza un pase editorial con IA sobre el capítulo activo: métricas deterministas + juicio editorial + propuestas con diff">Pase editorial con IA</button>
        </div>
        <div class="auditoria-categorias" id="auditoria-categorias"></div>
        <div class="auditoria-resultados" id="auditoria-resultados">
          <div class="empty-state">Pulsa "Ejecutar auditoría".</div>
        </div>`;
      const catsDiv = document.getElementById("auditoria-categorias");
      for (const c of AUDITORIA_CATEGORIAS) {
        const lbl = document.createElement("label");
        const inp = document.createElement("input");
        inp.type = "checkbox";
        inp.checked = true;
        inp.value = c.key;
        lbl.appendChild(inp);
        lbl.appendChild(document.createTextNode(" " + c.label));
        catsDiv.appendChild(lbl);
      }
      document.getElementById("auditoria-ejecutar").addEventListener("click", ejecutarAuditoria);
      document.getElementById("auditoria-ia").addEventListener("click", lanzarPaseEditorialIA);
      cont.dataset.montado = "1";
    }
  }

  async function lanzarPaseEditorialIA() {
    const ambito = document.getElementById("auditoria-ambito").value;
    const min = document.getElementById("auditoria-min").value || "1500";
    const max = document.getElementById("auditoria-max").value || "2500";

    let slug, promptTexto, tipoInforme;
    if (ambito === "actual") {
      if (!state.rutaActiva || !state.rutaActiva.startsWith("04_capitulos/")) {
        alert("Abre un capítulo (en 04_capitulos/) o cambia a 'Todo el proyecto'.");
        return;
      }
      slug = state.rutaActiva.replace(/^04_capitulos\//, "").replace(/\.md$/, "");
      tipoInforme = "capitulo";
      promptTexto = promptPaseEditorialCapitulo(slug, min, max);
    } else {
      tipoInforme = "proyecto";
      promptTexto = promptPaseEditorialProyecto(min, max);
    }

    // Asegurar que hay conversación; si no, el endpoint la crea.
    // Cambiar al modo editor para que se vean las propuestas cuando lleguen.
    cambiarModo("editor");
    // Envío por chat usando el mismo flujo de mensajes normal.
    const input = document.getElementById("chat-input");
    input.value = promptTexto;
    enviarMensajeChat();
  }

  function promptPaseEditorialCapitulo(slug, min, max) {
    return (
      `Pase editorial completo sobre el capítulo **${slug}**.

1. Llama a \`auditar_capitulo\` con slug="${slug}" y rango ${min}-${max} palabras para tener métricas deterministas (repeticiones, dicendi, tiempos, erratas, tics, coherencia canon).
2. Lee el capítulo (\`leer_fichero\`) y las fichas de los personajes que aparecen en la cabecera (\`leer_fichero\` por cada uno). Si hay raccord, escaleta o estilo relevantes, también.
3. Aplica juicio editorial sobre lo que la auditoría determinista NO puede ver:
   - Sobreexplicación / glosa / subrayado del narrador.
   - Efectismo, cliffhangers forzados, frases aisladas abusivas.
   - Voz propia de cada personaje en diálogo.
   - Atribuciones débiles, coletillas didácticas.
   - Raccord con el capítulo anterior.
   - Anacronismos o contradicciones con el canon.
4. Propón las correcciones con \`modificar_fichero\`. UN solo modificar_fichero con el capítulo completo reescrito respetando la voz del autor (mínima intervención, no reescritura); motivo breve explicando qué categorías tocaste.

No expliques todo en el chat; que el diff hable. Al final resume en 3-5 bullets qué cambiaste y qué dejaste pendiente por ser decisión del autor.`
    );
  }

  function promptPaseEditorialProyecto(min, max) {
    return (
      `Informe editorial global del proyecto.

1. Llama a \`auditar_capitulo\` con slug="proyecto" y rango ${min}-${max} palabras.
2. Identifica los 3-5 capítulos con problemas más graves (prioriza: dicendi con color > 50%, repeticiones excesivas, coherencia canon con gravedad alta, longitud muy fuera de rango).
3. NO propongas cambios todavía. Solo informe: por cada capítulo problemático, diagnóstico breve y qué intervenciones sugerirías. El autor decidirá cuáles atacar después uno a uno.`
    );
  }

  async function ejecutarAuditoria() {
    const btn = document.getElementById("auditoria-ejecutar");
    const resultados = document.getElementById("auditoria-resultados");
    const ambito = document.getElementById("auditoria-ambito").value;
    const min = document.getElementById("auditoria-min").value || "1500";
    const max = document.getElementById("auditoria-max").value || "2500";
    const categorias = Array.from(document.querySelectorAll("#auditoria-categorias input:checked"))
      .map((i) => i.value);

    if (ambito === "actual" && !state.rutaActiva) {
      resultados.innerHTML = '<div class="empty-state">Abre un capítulo primero o cambia a "Todo el proyecto".</div>';
      return;
    }
    if (ambito === "actual" && !state.rutaActiva.startsWith("04_capitulos/")) {
      resultados.innerHTML = '<div class="empty-state">La auditoría se aplica a capítulos (carpeta 04_capitulos/).</div>';
      return;
    }

    btn.disabled = true;
    btn.textContent = "Ejecutando…";
    resultados.innerHTML = '<div class="empty-state">Auditando…</div>';
    const params = new URLSearchParams();
    if (ambito === "actual") {
      const slug = state.rutaActiva.replace(/^04_capitulos\//, "").replace(/\.md$/, "");
      params.set("slug", slug);
    }
    if (categorias.length) params.set("categorias", categorias.join(","));
    params.set("min_palabras", min);
    params.set("max_palabras", max);

    try {
      const data = await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/auditoria?${params.toString()}`);
      pintarAuditoria(data);
    } catch (e) {
      resultados.innerHTML = `<div class="empty-state">Error: ${escape(String(e.message || e))}</div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = "Ejecutar auditoría";
    }
  }

  function pintarAuditoria(data) {
    const cont = document.getElementById("auditoria-resultados");
    cont.innerHTML = "";
    if (data.coherencia_global && data.coherencia_global.total_hallazgos) {
      const box = document.createElement("div");
      box.className = "auditoria-cap";
      box.innerHTML = `<div class="auditoria-cap-header"><h4>Coherencia global</h4><span class="meta">${data.coherencia_global.total_hallazgos} hallazgos</span></div>`;
      box.appendChild(renderCoherencia(data.coherencia_global.hallazgos));
      cont.appendChild(box);
    }
    for (const cap of data.capitulos || []) {
      cont.appendChild(renderCapituloAuditoria(cap));
    }
    if (!(data.capitulos || []).length) {
      cont.innerHTML = '<div class="empty-state">Sin capítulos en orden.json.</div>';
    }
  }

  function renderCapituloAuditoria(cap) {
    const box = document.createElement("div");
    box.className = "auditoria-cap";
    if (cap.error) {
      box.innerHTML = `<div class="auditoria-cap-header"><h4>${escape(cap.slug)}</h4><span class="meta err">${escape(cap.error)}</span></div>`;
      return box;
    }
    const header = document.createElement("div");
    header.className = "auditoria-cap-header";
    header.innerHTML =
      `<h4>${escape(cap.titulo || cap.slug)}</h4>` +
      `<span class="meta">${escape(cap.slug)}</span>`;
    const abrir = document.createElement("button");
    abrir.className = "abrir";
    abrir.textContent = "Abrir";
    abrir.addEventListener("click", () => {
      state.rutaActiva = cap.ruta;
      abrirFichero(cap.ruta);
      cambiarModo("editor");
    });
    header.appendChild(abrir);
    box.appendChild(header);

    if (cap.longitud) {
      const s = secc("Longitud");
      if (cap.longitud.fuera_rango) {
        s.appendChild(advertencia(`${cap.longitud.palabras} palabras (rango ${cap.longitud.minimo}–${cap.longitud.maximo})`));
      } else {
        s.appendChild(item(null, `${cap.longitud.palabras} palabras`, null, "ok"));
      }
      box.appendChild(s);
    }
    if (cap.dicendi) {
      const s = secc("Dicendi");
      s.appendChild(item(cap.dicendi.invisibles, "dijo/dice (invisibles)", null, "ok"));
      s.appendChild(item(cap.dicendi.color, `de color (${cap.dicendi.color_porcentaje}%)`, null, cap.dicendi.advertencia ? "warn" : null));
      if (cap.dicendi.advertencia) s.appendChild(advertencia(cap.dicendi.advertencia));
      for (const [v, n] of cap.dicendi.color_top || []) {
        s.appendChild(item(n, v, null));
      }
      box.appendChild(s);
    }
    if (cap.tiempos) {
      const s = secc("Tiempos verbales");
      s.appendChild(item(null, `Dominante: ${cap.tiempos.dominante || "—"} (presente ${cap.tiempos.pct_presente || 0}%, pasado ${cap.tiempos.pct_pasado || 0}%)`));
      if (cap.tiempos.advertencia) s.appendChild(advertencia(cap.tiempos.advertencia));
      box.appendChild(s);
    }
    if (cap.repeticiones_palabra) {
      const s = secc(`Repeticiones de palabra (${cap.repeticiones_palabra.length})`);
      if (!cap.repeticiones_palabra.length) s.appendChild(vacio());
      for (const r of cap.repeticiones_palabra) {
        s.appendChild(item(r.apariciones, r.palabra, `líneas ${r.lineas.slice(0,6).join(", ")}${r.lineas.length > 6 ? "…" : ""}${r.min_distancia_lineas != null ? ` · min dist ${r.min_distancia_lineas}l` : ""}`));
      }
      box.appendChild(s);
    }
    if (cap.repeticiones_ngrama) {
      const s = secc(`Repeticiones de frase 5-gram (${cap.repeticiones_ngrama.length})`);
      if (!cap.repeticiones_ngrama.length) s.appendChild(vacio());
      for (const r of cap.repeticiones_ngrama) {
        s.appendChild(item(r.apariciones, `"${r.ngrama}"`));
      }
      box.appendChild(s);
    }
    if (cap.tics) {
      const s = secc(`Tics / muletillas (${cap.tics.length})`);
      if (!cap.tics.length) s.appendChild(vacio("Sin tics configurados o sin matches."));
      for (const t of cap.tics) {
        s.appendChild(item(t.apariciones, t.tic, `líneas ${t.lineas.slice(0,6).join(", ")}`));
      }
      box.appendChild(s);
    }
    if (cap.erratas) {
      const s = secc(`Erratas (${cap.erratas.length})`);
      if (!cap.erratas.length) s.appendChild(item(null, "Sin erratas detectadas", null, "ok"));
      for (const e of cap.erratas) {
        const txt = e.tipo + (e.linea ? ` (línea ${e.linea})` : "") + (e.mensaje ? ` — ${e.mensaje}` : "");
        s.appendChild(item(null, txt, null, "warn"));
      }
      box.appendChild(s);
    }
    if (cap.cronologia) {
      const s = secc("Cronología extraída");
      if (!cap.cronologia.fechas.length && !cap.cronologia.dias_semana.length) {
        s.appendChild(vacio("Sin fechas/días explícitos."));
      }
      for (const f of cap.cronologia.fechas) {
        s.appendChild(item(null, `${f.dia} de ${f.mes}${f.anio ? " de " + f.anio : ""} · línea ${f.linea}`));
      }
      for (const d of cap.cronologia.dias_semana) {
        s.appendChild(item(null, `${d.dia_semana} · línea ${d.linea}`));
      }
      box.appendChild(s);
    }
    if (cap.coherencia) {
      const s = secc(`Coherencia canon (${cap.coherencia.total_hallazgos})`);
      if (!cap.coherencia.total_hallazgos) s.appendChild(item(null, "Sin hallazgos", null, "ok"));
      s.appendChild(renderCoherencia(cap.coherencia.hallazgos));
      box.appendChild(s);
    }

    return box;
  }

  function renderCoherencia(hallazgos) {
    const wrap = document.createElement("div");
    for (const h of hallazgos || []) {
      const clase = h.gravedad === "alta" ? "err" : h.gravedad === "media" ? "warn" : "";
      wrap.appendChild(item(null, `[${h.gravedad}] ${h.tipo}: ${h.mensaje}`, h.fichero, clase));
    }
    return wrap;
  }

  function secc(titulo) {
    const d = document.createElement("div");
    d.className = "auditoria-seccion";
    const h = document.createElement("h5");
    h.textContent = titulo;
    d.appendChild(h);
    return d;
  }

  function item(cant, valor, lineas, clase) {
    const d = document.createElement("div");
    d.className = "auditoria-item" + (clase ? " " + clase : "");
    if (cant != null) {
      const c = document.createElement("span");
      c.className = "cant";
      c.textContent = String(cant);
      d.appendChild(c);
    }
    const v = document.createElement("span");
    v.className = "valor";
    v.textContent = valor;
    d.appendChild(v);
    if (lineas) {
      const l = document.createElement("span");
      l.className = "lineas";
      l.textContent = lineas;
      d.appendChild(l);
    }
    return d;
  }

  function advertencia(texto) {
    const d = document.createElement("div");
    d.className = "auditoria-advertencia";
    d.textContent = texto;
    return d;
  }

  function vacio(texto) {
    const d = document.createElement("div");
    d.className = "auditoria-vacio";
    d.textContent = texto || "Nada que señalar.";
    return d;
  }

  // ----------------------------------------------------------- Modo audit
  async function cargarModoAudit() {
    const cont = document.getElementById("modo-audit");
    if (!state.proyectoSlug) {
      cont.innerHTML = '<div class="empty-state">Selecciona un proyecto.</div>';
      return;
    }
    if (!cont.dataset.montado) {
      cont.innerHTML =
        `<div class="audit-filtros">
          <input type="text" id="audit-fichero" placeholder="Ruta de fichero (opcional)" />
          <select id="audit-tipo">
            <option value="">Todos los tipos</option>
            <option value="ia_lectura">ia_lectura</option>
            <option value="ia_escritura_propuesta">ia_escritura_propuesta</option>
            <option value="ia_escritura_aplicada">ia_escritura_aplicada</option>
            <option value="ia_escritura_rechazada">ia_escritura_rechazada</option>
            <option value="usuario_edicion">usuario_edicion</option>
            <option value="usuario_reordenacion">usuario_reordenacion</option>
            <option value="sistema_init">sistema_init</option>
            <option value="sistema_restauracion">sistema_restauracion</option>
          </select>
          <input type="text" id="audit-buscar" placeholder="Buscar en texto" />
          <button type="button" id="audit-refrescar" class="btn-mini btn-editar">Filtrar</button>
        </div>
        <div class="audit-resumen" id="audit-resumen"></div>
        <div class="audit-lista" id="audit-lista"></div>`;
      document.getElementById("audit-refrescar").addEventListener("click", cargarAuditData);
      cont.dataset.montado = "1";
    }
    await cargarAuditData();
  }

  async function cargarAuditData() {
    const fichero = document.getElementById("audit-fichero").value.trim();
    const tipo = document.getElementById("audit-tipo").value;
    const buscar = document.getElementById("audit-buscar").value.trim();
    const params = new URLSearchParams();
    if (fichero) params.set("fichero", fichero);
    if (tipo) params.set("tipo", tipo);
    if (buscar) params.set("buscar", buscar);
    params.set("limite", "200");
    try {
      const [eventos, resumen] = await Promise.all([
        api(`/api/proyecto/${slugURL(state.proyectoSlug)}/audit?${params.toString()}`),
        api(`/api/proyecto/${slugURL(state.proyectoSlug)}/audit/resumen`),
      ]);
      pintarAuditResumen(resumen);
      pintarAuditLista(eventos.eventos || []);
    } catch (e) {
      document.getElementById("audit-lista").innerHTML =
        `<div class="empty-state">Error: ${e.message || e}</div>`;
    }
  }

  function pintarAuditResumen(r) {
    const el = document.getElementById("audit-resumen");
    const coste = (r.total_coste_eur || 0).toFixed(4);
    el.innerHTML =
      `<span><b>${r.total_eventos}</b> eventos</span>` +
      `<span>Coste total: <b>${coste} €</b></span>` +
      `<span>Tokens in: <b>${r.tokens_totales.input.toLocaleString()}</b></span>` +
      `<span>cached: <b>${r.tokens_totales.input_cached.toLocaleString()}</b></span>` +
      `<span>out: <b>${r.tokens_totales.output.toLocaleString()}</b></span>`;
  }

  function pintarAuditLista(eventos) {
    const cont = document.getElementById("audit-lista");
    cont.innerHTML = "";
    if (!eventos.length) {
      cont.innerHTML = '<div class="empty-state">Sin eventos con esos filtros.</div>';
      return;
    }
    for (const ev of eventos) {
      const div = document.createElement("div");
      div.className = "audit-evento";
      const detalle =
        (ev.fichero ? `${ev.fichero} ` : "") +
        (ev.mensaje_usuario ? `· ${ev.mensaje_usuario.slice(0, 80)}` : "") +
        (ev.motivo_ia ? `· ${ev.motivo_ia.slice(0, 80)}` : "") +
        (ev.commit_git ? ` · ${ev.commit_git.slice(0, 7)}` : "");
      const coste = ev.coste_eur ? `${Number(ev.coste_eur).toFixed(4)} €` : "";
      div.innerHTML =
        `<span class="ts">${ev.timestamp.slice(0, 19).replace("T", " ")}</span>` +
        `<span class="tipo">${ev.tipo}</span>` +
        `<span class="detalle">${escape(detalle)}</span>` +
        `<span class="coste">${coste}</span>`;
      cont.appendChild(div);
    }
  }

  // ----------------------------------------------------------- Menú contextual
  let menuActual = null;

  function mostrarMenuContextual(x, y, items) {
    cerrarMenuContextual();
    const menu = document.createElement("div");
    menu.className = "menu-contextual";
    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
    for (const it of items) {
      const d = document.createElement("div");
      d.className = "menu-item" + (it.peligro ? " peligro" : "");
      d.textContent = it.texto;
      d.addEventListener("click", () => {
        cerrarMenuContextual();
        it.accion();
      });
      menu.appendChild(d);
    }
    document.body.appendChild(menu);
    menuActual = menu;
    setTimeout(() => document.addEventListener("click", cerrarMenuContextual, { once: true }), 0);
  }

  function cerrarMenuContextual() {
    if (menuActual) {
      menuActual.remove();
      menuActual = null;
    }
  }

  function accionRenombrar(ruta) {
    const slugActual = ruta.split("/").pop().replace(/\.md$/, "");
    mostrarModal(
      `Renombrar ${ruta}`,
      [{ name: "nuevo_slug", label: "Nuevo slug", default: slugActual, pattern: "[a-z0-9_]+" }],
      async (v) => {
        const ns = slugify(v.nuevo_slug);
        if (!ns) throw new Error("Slug vacío.");
        const resp = await fetch(`/api/proyecto/${slugURL(state.proyectoSlug)}/fichero/renombrar`, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ruta, nuevo_slug: ns }),
        });
        if (!resp.ok) throw new Error(await resp.text());
        const data = await resp.json();
        await Promise.all([cargarArbol(), cargarGitStatus()]);
        if (state.rutaActiva === ruta) {
          state.rutaActiva = data.nueva_ruta;
          await abrirFichero(data.nueva_ruta);
        }
      }
    );
  }

  async function accionBorrar(ruta) {
    if (!confirm(`¿Borrar definitivamente ${ruta}?\n(queda en el historial Git, se puede restaurar)`)) return;
    try {
      const resp = await fetch(
        `/api/proyecto/${slugURL(state.proyectoSlug)}/fichero?ruta=${encodeURIComponent(ruta)}`,
        { method: "DELETE", credentials: "same-origin" }
      );
      if (!resp.ok) throw new Error(await resp.text());
      if (state.rutaActiva === ruta) {
        state.rutaActiva = null;
        state.editor.value("");
        document.getElementById("workspace-titulo").textContent = "— selecciona un fichero —";
      }
      await Promise.all([cargarArbol(), cargarGitStatus()]);
    } catch (e) {
      alert("Error al borrar: " + (e.message || e));
    }
  }

  function accionVerHistorial(ruta) {
    state.rutaActiva = ruta;
    cambiarModo("historial");
  }

  function accionMejorarConIA(ruta) {
    if (!state.proyectoSlug) return alert("Selecciona un proyecto.");
    cambiarModo("editor");
    const input = document.getElementById("chat-input");
    input.value = promptMejorarDocumento(ruta);
    enviarMensajeChat();
  }

  function tipoDocumento(ruta) {
    if (ruta.startsWith("04_capitulos/")) return "capitulo";
    if (ruta.startsWith("01_personajes/")) return "ficha_personaje";
    if (ruta.startsWith("02_mundo/")) {
      const slug = ruta.split("/").pop().replace(/\.md$/, "");
      if (["worldbuilding", "glosario", "mapa"].includes(slug)) return "mundo_general";
      return "ficha_lugar";
    }
    const tabla = {
      "03_estructura/actos.md": "actos",
      "03_estructura/escaleta.md": "escaleta",
      "03_estructura/relaciones.md": "relaciones",
      "03_estructura/cronologia.md": "cronologia",
      "03_estructura/pov.md": "pov",
      "05_control/estilo.md": "estilo",
      "05_control/raccord.md": "raccord",
      "05_control/bitacora.md": "bitacora",
      "00_concepto/premisa.md": "premisa",
      "00_concepto/sinopsis.md": "sinopsis",
      "00_concepto/tesis.md": "tesis",
      "06_revision/plan_correcciones.md": "plan_correcciones",
      "06_revision/notas_editoriales.md": "notas_editoriales",
    };
    return tabla[ruta] || "generico";
  }

  function guiaPropagacion(tipo) {
    const g = {
      capitulo: [
        "03_estructura/escaleta.md (verificar que la entrada del cap sigue fiel)",
        "03_estructura/relaciones.md (si aparecen personajes/lugares nuevos)",
        "05_control/raccord.md (si se siembran detalles que deben persistir)",
        "Fichas de personajes presentes (aparece_en, conocimiento, voz)",
      ],
      ficha_personaje: [
        "03_estructura/relaciones.md (sección 'Por personaje')",
        "05_control/raccord.md (rasgos físicos, tics verbales)",
        "Capítulos listados en aparece_en (solo si contradicción grave)",
      ],
      ficha_lugar: [
        "03_estructura/relaciones.md",
        "05_control/raccord.md (detalles geográficos, atmósfera)",
        "Capítulos listados en aparece_en (solo si contradicción)",
      ],
      mundo_general: [
        "Fichas de lugares (si cambian reglas del mundo)",
        "05_control/raccord.md",
      ],
      actos: [
        "03_estructura/escaleta.md (¿los caps siguen el nuevo arco?)",
        "03_estructura/pov.md",
        "00_concepto/sinopsis.md",
      ],
      escaleta: [
        "03_estructura/actos.md (debe encajar con la macro)",
        "03_estructura/relaciones.md",
        "03_estructura/cronologia.md",
      ],
      relaciones: [
        "Fichas de personajes (si hay inconsistencia)",
        "05_control/raccord.md",
      ],
      cronologia: [
        "Fichas de personajes (aparece_en)",
        "03_estructura/escaleta.md",
      ],
      pov: [
        "03_estructura/escaleta.md (las asignaciones deben encajar)",
        "Cabeceras YAML de capítulos (solo si contradicción clara con pov.md)",
      ],
      estilo: [
        "05_control/raccord.md",
        "05_control/bitacora.md",
      ],
      raccord: [
        "Fichas de personajes y lugares (rasgos físicos)",
        "Capítulos afectados (solo si contradicción grave)",
      ],
      bitacora: [
        "No propaga: es registro histórico, no canon vivo.",
      ],
      premisa: [
        "00_concepto/sinopsis.md",
        "00_concepto/tesis.md",
        "03_estructura/actos.md",
      ],
      sinopsis: [
        "00_concepto/premisa.md",
        "00_concepto/tesis.md",
        "03_estructura/actos.md",
        "03_estructura/escaleta.md",
      ],
      tesis: [
        "00_concepto/premisa.md",
        "00_concepto/sinopsis.md",
        "05_control/estilo.md",
      ],
      plan_correcciones: [
        "No propaga: es lista de tareas. Puede actualizarse, no replica cambios.",
      ],
      notas_editoriales: [
        "No propaga: es veredicto global. No modifica el canon directamente.",
      ],
      generico: [
        "Usa listar_ficheros_proyecto y buscar_texto para localizar referencias a este documento.",
      ],
    };
    return (g[tipo] || g.generico).map((l) => "   - " + l).join("\n");
  }

  function promptMejorarDocumento(ruta) {
    const tipo = tipoDocumento(ruta);
    return (
`Mejora el documento **${ruta}** y propaga los cambios al resto del canon cuando sea necesario.

Flujo:

1. Lee \`${ruta}\` con leer_fichero.
2. Lee los documentos vecinos que podrían depender (según el tipo de fichero):
${guiaPropagacion(tipo)}
3. Aplica juicio editorial al documento principal:
   - Claridad y economía: ¿hay generalidades vacías, redundancia, pasos que sobran?
   - Coherencia interna: ¿se contradice a sí mismo?
   - Completud: ¿falta algo esencial que debería estar aquí?
   - Respeto al canon ya establecido en los vecinos.
4. Identifica qué vecinos deben actualizarse SI aplicamos el cambio del principal (propagación).
5. Registra las propuestas con \`modificar_fichero\` o \`crear_fichero\`:
   - UNA propuesta para ${ruta} con la versión mejorada.
   - UNA propuesta por cada vecino afectado, con motivo claro (qué cambio del principal lo justifica). Si no hay vecinos afectados, no inventes cambios: deja el principal y ya.
6. Reglas de seguridad:
   - NO toques capítulos redactados (04_capitulos con estado borrador_v2/revisado/cerrado) a menos que haya contradicción grave con el nuevo canon. Si la hay, propón añadir una entrada en 06_revision/plan_correcciones.md con la tarea a revisar manualmente, en vez de reescribir prosa.
   - NO elimines secciones completas sin explicarlo en el motivo.
7. Si alguna decisión del autor está pendiente (nombre, número, fecha), deja marcador [PENDIENTE: ...] en vez de inventar.

Al final resume en 3-5 bullets qué mejoraste del principal y qué propagaste.`
    );
  }

  // ----------------------------------------------------------- Drag & drop
  function enganchaDragDrop(elem, fichero, carpeta) {
    if (carpeta !== "04_capitulos") return;
    elem.draggable = true;
    elem.dataset.slug = fichero.slug;
    elem.addEventListener("dragstart", (e) => {
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", fichero.slug);
      elem.classList.add("dragging");
    });
    elem.addEventListener("dragend", () => elem.classList.remove("dragging"));
    elem.addEventListener("dragover", (e) => {
      e.preventDefault();
      elem.classList.add("drag-over");
    });
    elem.addEventListener("dragleave", () => elem.classList.remove("drag-over"));
    elem.addEventListener("drop", async (e) => {
      e.preventDefault();
      elem.classList.remove("drag-over");
      const draggedSlug = e.dataTransfer.getData("text/plain");
      if (!draggedSlug || draggedSlug === fichero.slug) return;
      await reordenarTrasDrag(draggedSlug, fichero.slug);
    });
  }

  async function reordenarTrasDrag(slugArrastrado, slugDestino) {
    const carpeta = state.arbol.carpetas.find((c) => c.nombre === "04_capitulos");
    if (!carpeta) return;
    const orden = carpeta.ficheros.map((f) => f.slug);
    const idxDrag = orden.indexOf(slugArrastrado);
    if (idxDrag < 0) return;
    orden.splice(idxDrag, 1);
    const idxDest = orden.indexOf(slugDestino);
    if (idxDest < 0) orden.push(slugArrastrado);
    else orden.splice(idxDest, 0, slugArrastrado);
    try {
      await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/reordenar`, {
        method: "POST",
        body: JSON.stringify({ nuevo_orden: orden }),
      });
      await Promise.all([cargarArbol(), cargarGitStatus()]);
    } catch (e) {
      alert("Error reordenando: " + (e.message || e));
    }
  }

  // ------------------------------------------------ Modo Claude Code (CLI)
  const cc = { overlay: null, pollingTimer: null, sesionId: null };

  function abrirPanelCC() {
    if (!state.proyectoSlug) { alert("Selecciona un proyecto."); return; }
    if (cc.overlay) { cerrarPanelCC(); return; }
    const div = document.createElement("div");
    div.className = "autonomo-overlay";
    div.innerHTML = `
      <div class="autonomo-header">
        <h2>⚡ Claude Code</h2>
        <button class="autonomo-close" type="button">✕</button>
      </div>
      <div class="autonomo-body" id="cc-body"></div>
      <div class="autonomo-footer">
        <div class="autonomo-acciones" id="cc-acciones"></div>
      </div>`;
    document.body.appendChild(div);
    cc.overlay = div;
    div.querySelector(".autonomo-close").addEventListener("click", cerrarPanelCC);
    refrescarPanelCC();
  }

  function cerrarPanelCC() {
    if (cc.pollingTimer) { clearInterval(cc.pollingTimer); cc.pollingTimer = null; }
    if (cc.overlay) { cc.overlay.remove(); cc.overlay = null; }
  }

  async function refrescarPanelCC() {
    if (!cc.overlay) return;
    try {
      const data = await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/autonomo/cc/ultima`);
      if (!data.activa || ["terminado","error","detenido"].includes(data.sesion.estado)) {
        pintarCCConfiguracion(data.activa ? data.sesion : null);
      } else {
        cc.sesionId = data.sesion.id;
        pintarCCEjecucion(data.sesion);
      }
    } catch (e) {
      document.getElementById("cc-body").innerHTML =
        `<div class="empty-state">Error: ${escape(String(e.message || e))}</div>`;
    }
  }

  function pintarCCConfiguracion(ultima) {
    const body = document.getElementById("cc-body");
    const ejemplos = [
      {t: "Redactar capítulo siguiente", p: "Redacta el siguiente capítulo según escaleta. Respeta golden_reference y feedback_autor si existen. Al terminar, ejecuta auditar_capitulo y corrige hallazgos graves."},
      {t: "Pase editorial a capítulo activo", p: state.rutaActiva && state.rutaActiva.startsWith("04_capitulos/")
        ? `Haz un pase editorial a ${state.rutaActiva.split("/").pop().replace(/\\.md$/,"")}: audítalo, detecta sobreexplicación/efectismo/voz, corrige. No reescribas si no hace falta.`
        : "(abre un capítulo para esta opción)"},
      {t: "Propagar canon desde fichero X", p: "Lee un documento que te indicaré, mejóralo y actualiza los demás del canon que dependen de él. Commitea cada cambio por separado."},
      {t: "Construir biblia de personajes", p: "Crea fichas completas de personajes principales en 01_personajes/ a partir de la sinopsis y la escaleta. Coherente entre sí. Una por personaje."},
      {t: "Continuar plan_autonomo.md", p: "Lee 05_control/plan_autonomo.md y ejecuta las tareas pendientes marcadas [ ]. Marca [x] al completar. Si no hay plan, créalo primero."},
    ];
    body.innerHTML = `
      ${ultima ? `<div class="autonomo-estado ${ultima.estado === 'terminado' ? 'terminado' : 'error'}">
        <span class="tag">${ultima.estado}</span>
        <b> · última sesión</b>
        ${ultima.error ? `<div style="margin-top:4px">${escape(ultima.error)}</div>` : ""}
      </div>` : ""}
      <div class="autonomo-seccion">
        <h3>Tarea</h3>
        <textarea id="cc-tarea" rows="5" style="width:100%;background:#0c1014;color:var(--text);border:1px solid var(--panel-border);padding:8px;font-size:13px;font-family:inherit;border-radius:3px"></textarea>
        <div class="autonomo-forma" style="margin-top:8px">
          <label>Modelo
            <select id="cc-modelo">
              <option value="">Default</option>
              <option value="claude-haiku-4-5">Haiku</option>
              <option value="claude-sonnet-4-6" selected>Sonnet</option>
              <option value="claude-opus-4-7">Opus</option>
            </select>
          </label>
          <label>
            <input type="checkbox" id="cc-permitir-cerrados" /> Permitir editar capítulos cerrados/revisados
          </label>
        </div>
      </div>
      <div class="autonomo-seccion">
        <h3>Plantillas</h3>
        <div id="cc-plantillas" style="display:flex;flex-direction:column;gap:4px"></div>
      </div>`;
    const cont = document.getElementById("cc-plantillas");
    for (const e of ejemplos) {
      const b = document.createElement("button");
      b.className = "btn-mini btn-editar";
      b.style.textAlign = "left";
      b.textContent = e.t;
      b.addEventListener("click", () => { document.getElementById("cc-tarea").value = e.p; });
      cont.appendChild(b);
    }
    document.getElementById("cc-acciones").innerHTML = "";
    const btn = document.createElement("button");
    btn.textContent = "Lanzar Claude Code";
    btn.addEventListener("click", lanzarCC);
    document.getElementById("cc-acciones").appendChild(btn);
  }

  async function lanzarCC() {
    const tarea = document.getElementById("cc-tarea").value.trim();
    if (!tarea) { alert("Escribe la tarea."); return; }
    const modelo = document.getElementById("cc-modelo").value || undefined;
    const permitirCerrados = document.getElementById("cc-permitir-cerrados").checked;
    try {
      const resp = await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/autonomo/cc/lanzar`, {
        method: "POST",
        body: JSON.stringify({ tarea, modelo, permitir_cerrados: permitirCerrados }),
      });
      cc.sesionId = resp.sesion_id;
      if (cc.pollingTimer) clearInterval(cc.pollingTimer);
      cc.pollingTimer = setInterval(pollCC, 2000);
      await refrescarPanelCC();
    } catch (e) {
      alert("No se pudo lanzar: " + (e.message || e));
    }
  }

  async function pollCC() {
    if (!cc.sesionId || !cc.overlay) return;
    try {
      const sesion = await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/autonomo/cc/estado/${cc.sesionId}`);
      pintarCCEjecucion(sesion);
      if (["terminado","error","detenido"].includes(sesion.estado)) {
        if (cc.pollingTimer) { clearInterval(cc.pollingTimer); cc.pollingTimer = null; }
        // Refrescar árbol/git tras terminar.
        try { await Promise.all([cargarArbol(), cargarGitStatus()]); } catch (_) {}
      }
    } catch (_) { /* ignore */ }
  }

  function pintarCCEjecucion(sesion) {
    const body = document.getElementById("cc-body");
    const claseEstado = {
      "arrancando": "",
      "ejecutando": "",
      "terminado": "terminado",
      "error": "error",
      "detenido": "error",
    }[sesion.estado] || "";
    const duracion = sesion.fin ? (sesion.fin - sesion.inicio).toFixed(1) : (Math.max(0, Date.now()/1000 - sesion.inicio)).toFixed(1);
    body.innerHTML = `
      <div class="autonomo-estado ${claseEstado}">
        <span class="tag">${sesion.estado}</span>
        <b> · modelo ${sesion.modelo || 'default'}</b>
        <div class="autonomo-metricas">
          <div><b>${duracion}s</b><span>duración</span></div>
          <div><b>${sesion.total_lineas}</b><span>líneas log</span></div>
          <div><b>${sesion.pid || '—'}</b><span>pid</span></div>
        </div>
      </div>
      <div class="autonomo-seccion">
        <h3>Salida de Claude Code</h3>
        <div class="autonomo-log" id="cc-log" style="max-height:420px"></div>
      </div>`;
    const logEl = document.getElementById("cc-log");
    logEl.textContent = (sesion.log_lines || []).join("\n") || "(esperando salida...)";
    logEl.scrollTop = logEl.scrollHeight;
    const acciones = document.getElementById("cc-acciones");
    acciones.innerHTML = "";
    if (["arrancando","ejecutando"].includes(sesion.estado)) {
      const d = document.createElement("button");
      d.className = "detener";
      d.textContent = "Detener sesión";
      d.addEventListener("click", async () => {
        if (!confirm("Detener la sesión de Claude Code?")) return;
        await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/autonomo/cc/detener/${sesion.id}`, {
          method: "POST", body: "{}"
        });
        await refrescarPanelCC();
      });
      acciones.appendChild(d);
    } else {
      const n = document.createElement("button");
      n.textContent = "Nueva sesión";
      n.addEventListener("click", () => pintarCCConfiguracion(sesion));
      acciones.appendChild(n);
    }
  }

  // ------------------------------------------------------ Modo autónomo
  const autonomo = {
    overlay: null,
    polling: false,
    loopActivo: false,
    log: [],
  };

  function abrirPanelAutonomo() {
    if (!state.proyectoSlug) { alert("Selecciona un proyecto."); return; }
    if (autonomo.overlay) { autonomo.overlay.remove(); autonomo.overlay = null; return; }
    const div = document.createElement("div");
    div.className = "autonomo-overlay";
    div.innerHTML = `
      <div class="autonomo-header">
        <h2>🤖 Modo autónomo</h2>
        <button class="autonomo-close" type="button">✕</button>
      </div>
      <div class="autonomo-body" id="autonomo-body"></div>
      <div class="autonomo-footer">
        <div class="autonomo-acciones" id="autonomo-acciones"></div>
      </div>`;
    document.body.appendChild(div);
    autonomo.overlay = div;
    div.querySelector(".autonomo-close").addEventListener("click", () => cerrarPanelAutonomo());
    refrescarPanelAutonomo();
  }

  function cerrarPanelAutonomo() {
    autonomo.loopActivo = false;
    if (autonomo.overlay) { autonomo.overlay.remove(); autonomo.overlay = null; }
  }

  async function refrescarPanelAutonomo() {
    if (!autonomo.overlay) return;
    try {
      const data = await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/autonomo/estado`);
      if (!data.activa) {
        pintarConfiguracionInicial();
      } else {
        pintarPanelEjecucion(data);
      }
    } catch (e) {
      document.getElementById("autonomo-body").innerHTML =
        `<div class="empty-state">Error: ${escape(String(e.message || e))}</div>`;
    }
  }

  function pintarConfiguracionInicial() {
    const body = document.getElementById("autonomo-body");
    body.innerHTML = `
      <div class="autonomo-seccion">
        <h3>Configuración inicial</h3>
        <div class="autonomo-forma">
          <label>Fase
            <select id="auto-fase">
              <option value="todo">Todo (concepción → revisión)</option>
              <option value="concepcion">Concepción</option>
              <option value="estructura">Estructura</option>
              <option value="personajes">Personajes</option>
              <option value="mundo">Mundo</option>
              <option value="redaccion">Redacción</option>
              <option value="revision">Revisión</option>
            </select>
          </label>
          <label>Modelo
            <select id="auto-modelo">
              <option value="">Default del proyecto</option>
              <option value="claude-haiku-4-5">Haiku · barato</option>
              <option value="claude-sonnet-4-6">Sonnet · redacción</option>
              <option value="claude-opus-4-7">Opus · máxima calidad</option>
            </select>
          </label>
          <label>Presupuesto (€)
            <input type="number" id="auto-presupuesto" value="5" step="0.5" min="0.5" max="200" />
            <span class="ayuda">Hard cap. Al alcanzarlo, el loop se detiene.</span>
          </label>
          <label>Tope de cola de propuestas
            <input type="number" id="auto-cola" value="15" min="5" max="50" />
            <span class="ayuda">Si la cola de propuestas pendientes de aprobar llega aquí, pausa.</span>
          </label>
        </div>
      </div>
      <div class="autonomo-seccion">
        <h3>Qué hace el modo autónomo</h3>
        <div class="autonomo-log" style="max-height:none">La IA lee el plan en <code>05_control/plan_autonomo.md</code>, elige la siguiente tarea, la ejecuta, actualiza el plan y avanza. Pausa sola cuando: hay preguntas para ti, la cola de propuestas se llena, el presupuesto se agota, detecta un bucle, o ha terminado la fase.

Antes de arrancar, opcionalmente pon un párrafo de tu prosa en <code>05_control/golden_reference.md</code> como referencia de voz.</div>
      </div>`;

    document.getElementById("autonomo-acciones").innerHTML = "";
    const btn = document.createElement("button");
    btn.textContent = "Iniciar ejecución";
    btn.addEventListener("click", iniciarAutonomo);
    document.getElementById("autonomo-acciones").appendChild(btn);
  }

  async function iniciarAutonomo() {
    const body = {
      fase: document.getElementById("auto-fase").value,
      modelo: document.getElementById("auto-modelo").value || undefined,
      presupuesto_eur: parseFloat(document.getElementById("auto-presupuesto").value) || 5,
      max_propuestas_cola: parseInt(document.getElementById("auto-cola").value, 10) || 15,
    };
    try {
      await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/autonomo/iniciar`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      autonomo.loopActivo = true;
      autonomo.log = [];
      await refrescarPanelAutonomo();
      arrancarLoop();
    } catch (e) {
      alert("No se pudo iniciar: " + (e.message || e));
    }
  }

  function pintarPanelEjecucion(data) {
    const body = document.getElementById("autonomo-body");
    const e = data.ejecucion;
    const pct = e.presupuesto_eur ? Math.min(100, 100 * e.coste_acumulado_eur / e.presupuesto_eur) : 0;
    const estadoClase = {
      "ejecutando": "",
      "pausado": "pausado",
      "esperando_autor": "pausado",
      "esperando_revision": "pausado",
      "detenido": "error",
      "error_presupuesto": "error",
      "error_stuck": "error",
      "terminado": "terminado",
    }[e.estado] || "";

    body.innerHTML = `
      <div class="autonomo-estado ${estadoClase}">
        <span class="tag">${e.estado}</span>
        <b> · fase ${e.fase}</b>
        ${e.razon_pausa ? `<div style="margin-top:4px">${escape(e.razon_pausa)}</div>` : ""}
        <div class="autonomo-metricas">
          <div><b>${e.coste_acumulado_eur.toFixed(4)}&nbsp;€</b><span>de ${e.presupuesto_eur.toFixed(2)}&nbsp;€ (${pct.toFixed(0)}%)</span></div>
          <div><b>${e.pasos_ejecutados}</b><span>pasos ejecutados</span></div>
          <div><b>${data.cola_propuestas}</b><span>propuestas en cola</span></div>
        </div>
      </div>
      ${data.preguntas_pendientes && data.preguntas_pendientes.length ? `
        <div class="autonomo-seccion">
          <h3>Preguntas del autor (${data.preguntas_pendientes.length})</h3>
          <div id="preguntas-lista"></div>
        </div>` : ""}
      <div class="autonomo-seccion">
        <h3>Actividad reciente</h3>
        <div class="autonomo-log" id="auto-log">${autonomo.log.slice(-20).map((l) => escape(l)).join("\n") || "(sin actividad aún)"}</div>
      </div>`;

    if (data.preguntas_pendientes && data.preguntas_pendientes.length) {
      const cont = document.getElementById("preguntas-lista");
      for (const p of data.preguntas_pendientes) {
        const d = document.createElement("div");
        d.className = "autonomo-pregunta";
        d.innerHTML = `
          <div class="p">${escape(p.pregunta)}</div>
          ${p.contexto ? `<div class="c">${escape(p.contexto)}</div>` : ""}
          <textarea rows="2" placeholder="Respuesta..."></textarea>
          <button>Responder y reanudar</button>`;
        const ta = d.querySelector("textarea");
        d.querySelector("button").addEventListener("click", async () => {
          const r = ta.value.trim();
          if (!r) return;
          await api(
            `/api/proyecto/${slugURL(state.proyectoSlug)}/autonomo/preguntas/${p.id}/responder`,
            { method: "POST", body: JSON.stringify({ respuesta: r }) }
          );
          autonomo.loopActivo = true;
          await refrescarPanelAutonomo();
          arrancarLoop();
        });
        cont.appendChild(d);
      }
    }

    // Acciones del footer según estado
    const acc = document.getElementById("autonomo-acciones");
    acc.innerHTML = "";
    if (e.estado === "ejecutando") {
      const p = document.createElement("button"); p.className = "pausar"; p.textContent = "Pausar";
      p.addEventListener("click", async () => {
        autonomo.loopActivo = false;
        await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/autonomo/pausar`, { method: "POST", body: "{}" });
        await refrescarPanelAutonomo();
      });
      acc.appendChild(p);
    } else if (["pausado", "esperando_revision"].includes(e.estado)) {
      const r = document.createElement("button"); r.textContent = "Reanudar";
      r.addEventListener("click", async () => {
        try {
          await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/autonomo/reanudar`, { method: "POST", body: "{}" });
          autonomo.loopActivo = true;
          await refrescarPanelAutonomo();
          arrancarLoop();
        } catch (e) { alert(e.message || e); }
      });
      acc.appendChild(r);
    } else if (e.estado === "esperando_autor") {
      const info = document.createElement("button");
      info.textContent = "Responde las preguntas para reanudar";
      info.disabled = true;
      acc.appendChild(info);
    }
    const d = document.createElement("button"); d.className = "detener"; d.textContent = "Detener";
    d.addEventListener("click", async () => {
      if (!confirm("Detener la ejecución autónoma? No se puede reanudar después.")) return;
      autonomo.loopActivo = false;
      await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/autonomo/detener`, { method: "POST", body: "{}" });
      await refrescarPanelAutonomo();
    });
    acc.appendChild(d);
  }

  async function arrancarLoop() {
    while (autonomo.loopActivo) {
      try {
        const resp = await api(
          `/api/proyecto/${slugURL(state.proyectoSlug)}/autonomo/paso`,
          { method: "POST", body: "{}" }
        );
        const snippet = (resp.mensaje_asistente || "").split("\n").slice(0, 2).join(" · ").slice(0, 200);
        autonomo.log.push(`· paso ${resp.ejecucion.pasos_ejecutados} · ${resp.coste_paso_eur.toFixed(4)}€ · props:${resp.propuestas_nuevas} preg:${resp.preguntas_nuevas}${snippet ? " · " + snippet : ""}`);
        await refrescarPanelAutonomo();
        if (resp.pausado) {
          autonomo.loopActivo = false;
          break;
        }
        await new Promise((r) => setTimeout(r, 1500));
      } catch (e) {
        autonomo.log.push("· ERROR: " + (e.message || e));
        autonomo.loopActivo = false;
        await refrescarPanelAutonomo();
        break;
      }
    }
    // Refrescar árbol y git tras ronda autónoma (pueden haberse aplicado propuestas vía fichero).
    try { await Promise.all([cargarArbol(), cargarGitStatus()]); } catch (_) { /* ignore */ }
  }

  // ----------------------------------------------------------------- Init
  document.addEventListener("DOMContentLoaded", async () => {
    inicializarEditor();
    montarChat();
    montarModos();
    document.getElementById("proyecto-select").addEventListener("change", (e) => {
      seleccionarProyecto(e.target.value);
    });
    document.getElementById("btn-nueva-novela").addEventListener("click", abrirModalNuevaNovela);
    document.getElementById("btn-nueva-saga").addEventListener("click", abrirModalNuevaSaga);
    document.getElementById("btn-nuevo-libro").addEventListener("click", abrirModalNuevoLibro);
    document.getElementById("btn-exportar-epub").addEventListener("click", () => {
      if (!state.proyectoSlug) return alert("Selecciona un proyecto.");
      window.location = `/api/proyecto/${slugURL(state.proyectoSlug)}/export/epub`;
    });
    document.getElementById("btn-configurar-remoto").addEventListener("click", abrirModalRemoto);
    document.getElementById("btn-autonomo").addEventListener("click", abrirPanelAutonomo);
    document.getElementById("btn-cc").addEventListener("click", abrirPanelCC);
    document.getElementById("btn-deshacer").addEventListener("click", async () => {
      if (!state.proyectoSlug) return;
      if (!confirm("Revertir el último commit del proyecto activo? Se crea un commit nuevo que invierte los cambios.")) return;
      try {
        await api(`/api/proyecto/${slugURL(state.proyectoSlug)}/deshacer`, {
          method: "POST", body: JSON.stringify({}),
        });
        await Promise.all([cargarArbol(), cargarGitStatus()]);
        if (state.rutaActiva) await refrescarFicheroActivo();
      } catch (e) {
        alert("Error: " + (e.message || e));
      }
    });
    try {
      await cargarProyectos();
    } catch (e) {
      console.error(e);
    }
  });
})();
