/**
 * Main application logic for Copper Town PWA.
 */
(function () {
  const $ = (s) => document.querySelector(s);
  const msgContainer = $("#messages");
  const input = $("#input");
  const btnSend = $("#btn-send");
  const agentSelect = $("#agent-select");
  const btnNew = $("#btn-new");
  const btnSettings = $("#btn-settings");
  const settingsPanel = $("#settings-panel");
  const cfgUrl = $("#cfg-url");
  const cfgKey = $("#cfg-key");
  const sessionList = $("#session-list");

  let api = null;
  let sending = false;

  // ── Init ──

  function initAPI() {
    api = new CopperAPI(Store.apiUrl, Store.apiKey);
  }

  async function init() {
    initAPI();

    // Register service worker
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }

    try {
      const agents = await api.getAgents();
      agentSelect.innerHTML = "";
      for (const a of agents) {
        const opt = document.createElement("option");
        opt.value = a.slug;
        opt.textContent = a.name;
        agentSelect.appendChild(opt);
      }
      if (Store.agent && agents.some((a) => a.slug === Store.agent)) {
        agentSelect.value = Store.agent;
      } else if (agents.length) {
        Store.agent = agents[0].slug;
      }
    } catch (e) {
      addError("Failed to load agents: " + e.message);
      return;
    }

    // Try to restore session
    if (Store.sessionId) {
      try {
        const msgs = await api.getMessages(Store.sessionId);
        for (const m of msgs) addMessage(m.role, m.content);
      } catch {
        Store.sessionId = "";
      }
    }

    if (!Store.sessionId) {
      await newSession();
    }
  }

  // ── Sessions ──

  async function newSession() {
    const slug = agentSelect.value;
    if (!slug) return;
    Store.agent = slug;
    msgContainer.innerHTML = "";

    try {
      const sess = await api.createSession(slug);
      Store.sessionId = sess.session_id;
    } catch (e) {
      addError("Failed to create session: " + e.message);
    }
  }

  // ── Messages ──

  function addMessage(role, content) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    div.textContent = content;
    msgContainer.appendChild(div);
    scrollBottom();
    return div;
  }

  function addError(text) {
    return addMessage("error", text);
  }

  function addTaskTree(tasks) {
    const n = tasks.length;
    const wrap = document.createElement("div");
    wrap.className = "task-tree";

    const header = document.createElement("div");
    header.className = "task-tree-header";
    header.innerHTML = `<span class="task-tree-dot">●</span> ${n} ${n === 1 ? "agent" : "agents"} launched`;
    wrap.appendChild(header);

    tasks.forEach((t, i) => {
      const isLast = i === tasks.length - 1;
      const item = document.createElement("div");
      item.className = "task-tree-item";

      const row = document.createElement("div");
      row.className = "task-tree-row";
      row.innerHTML = `<span class="task-tree-conn">${isLast ? "└──" : "├──"}</span> <strong>${t.name}</strong>`;
      item.appendChild(row);

      const sub = document.createElement("div");
      sub.className = "task-tree-sub";
      sub.innerHTML = `<span class="task-tree-pipe">${isLast ? "\u00a0\u00a0\u00a0\u00a0" : "│\u00a0\u00a0\u00a0"}</span>└ Running in the background`;
      item.appendChild(sub);

      wrap.appendChild(item);
    });

    msgContainer.appendChild(wrap);
    scrollBottom();
  }

  function scrollBottom() {
    msgContainer.scrollTop = msgContainer.scrollHeight;
  }

  // ── Send ──

  async function send() {
    const text = input.value.trim();
    if (!text || sending) return;
    if (!Store.sessionId) {
      addError("No active session. Create one first.");
      return;
    }

    sending = true;
    btnSend.disabled = true;
    input.value = "";
    autoResize();

    addMessage("user", text);

    const bubble = addMessage("assistant typing", "");
    let pendingText = "";
    let rafQueued = false;

    function flushTokens() {
      bubble.textContent = pendingText;
      scrollBottom();
      rafQueued = false;
    }

    try {
      await api.sendMessage(Store.sessionId, text, {
        onToken(t) {
          pendingText += t;
          if (!rafQueued) {
            rafQueued = true;
            requestAnimationFrame(flushTokens);
          }
        },
        onDone(content) {
          bubble.classList.remove("typing");
          bubble.textContent = content;
          scrollBottom();
        },
        onError(err) {
          bubble.remove();
          addError(err);
        },
        onTasks(tasks) {
          addTaskTree(tasks);
        },
      });
    } catch (e) {
      bubble.remove();
      addError("Network error: " + e.message);
    }

    sending = false;
    btnSend.disabled = false;
    input.focus();
  }

  // ── Input auto-resize ──

  function autoResize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  }

  input.addEventListener("input", autoResize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  btnSend.addEventListener("click", send);

  // ── Agent select ──

  agentSelect.addEventListener("change", () => {
    Store.agent = agentSelect.value;
  });

  // ── New session ──

  btnNew.addEventListener("click", () => newSession());

  // ── Settings ──

  btnSettings.addEventListener("click", async () => {
    cfgUrl.value = Store.apiUrl;
    cfgKey.value = Store.apiKey;
    settingsPanel.classList.remove("hidden");

    // Load sessions
    sessionList.innerHTML = "";
    try {
      const sessions = await api.getSessions();
      for (const s of sessions) {
        const item = document.createElement("div");
        item.className = "session-item";

        const info = document.createElement("span");
        info.textContent = `${s.agent} (${s.messages} msgs)`;
        info.addEventListener("click", async () => {
          Store.sessionId = s.id;
          msgContainer.innerHTML = "";
          try {
            const msgs = await api.getMessages(s.id);
            for (const m of msgs) addMessage(m.role, m.content);
          } catch (e) {
            addError("Failed to load messages: " + e.message);
          }
          settingsPanel.classList.add("hidden");
        });

        const del = document.createElement("button");
        del.className = "session-delete";
        del.textContent = "\u00D7";
        del.addEventListener("click", async (e) => {
          e.stopPropagation();
          try {
            await api.deleteSession(s.id);
            item.remove();
            if (Store.sessionId === s.id) {
              Store.sessionId = "";
              msgContainer.innerHTML = "";
            }
          } catch (err) {
            addError("Failed to delete: " + err.message);
          }
        });

        item.appendChild(info);
        item.appendChild(del);
        sessionList.appendChild(item);
      }
    } catch {
      // ignore
    }
  });

  $("#btn-settings-save").addEventListener("click", () => {
    Store.apiUrl = cfgUrl.value.trim() || location.origin;
    Store.apiKey = cfgKey.value.trim();
    initAPI();
    settingsPanel.classList.add("hidden");
  });

  $("#btn-settings-cancel").addEventListener("click", () => {
    settingsPanel.classList.add("hidden");
  });

  $(".settings-backdrop").addEventListener("click", () => {
    settingsPanel.classList.add("hidden");
  });

  // ── Boot ──

  init();
})();
