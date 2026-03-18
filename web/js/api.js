/**
 * API client for Copper Town HTTP API with SSE streaming.
 */
class CopperAPI {
  constructor(baseUrl, apiKey) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.apiKey = apiKey;
  }

  _headers(json = false) {
    const h = {};
    if (this.apiKey) h["X-API-Key"] = this.apiKey;
    if (json) h["Content-Type"] = "application/json";
    return h;
  }

  async _checkResponse(res) {
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || `HTTP ${res.status}`);
    }
    return res;
  }

  async _fetch(path, opts = {}) {
    const res = await fetch(this.baseUrl + path, {
      ...opts,
      headers: { ...this._headers(!!opts.body), ...opts.headers },
    });
    return this._checkResponse(res);
  }

  async getAgents() {
    const res = await this._fetch("/api/agents");
    return res.json();
  }

  async createSession(agentSlug) {
    const res = await this._fetch("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ agent: agentSlug }),
    });
    return res.json();
  }

  async getSessions() {
    const res = await this._fetch("/api/sessions");
    return res.json();
  }

  async deleteSession(id) {
    await this._fetch(`/api/sessions/${id}`, { method: "DELETE" });
  }

  async getMessages(sessionId) {
    const res = await this._fetch(`/api/sessions/${sessionId}/messages`);
    return res.json();
  }

  async sendMessage(sessionId, content, { onToken, onDone, onError, onTasks }) {
    const res = await fetch(this.baseUrl + `/api/sessions/${sessionId}/messages`, {
      method: "POST",
      headers: this._headers(true),
      body: JSON.stringify({ content }),
    });

    try {
      await this._checkResponse(res);
    } catch (e) {
      onError(e.message);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep incomplete line

      let eventType = "";
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          const data = line.slice(6);
          try {
            const parsed = JSON.parse(data);
            if (eventType === "token") onToken(parsed.t);
            else if (eventType === "done") onDone(parsed.content);
            else if (eventType === "error") onError(parsed.error);
            else if (eventType === "tasks" && onTasks) onTasks(parsed);
          } catch (e) {
            // skip malformed data
          }
        }
      }
    }
  }
}
