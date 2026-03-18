/**
 * localStorage wrapper for app config and session state.
 */
const Store = {
  get apiUrl() {
    return localStorage.getItem("ct_apiUrl") || location.origin;
  },
  set apiUrl(v) {
    localStorage.setItem("ct_apiUrl", v);
  },

  get apiKey() {
    return localStorage.getItem("ct_apiKey") || "";
  },
  set apiKey(v) {
    localStorage.setItem("ct_apiKey", v);
  },

  get sessionId() {
    return localStorage.getItem("ct_sessionId") || "";
  },
  set sessionId(v) {
    localStorage.setItem("ct_sessionId", v);
  },

  get agent() {
    return localStorage.getItem("ct_agent") || "";
  },
  set agent(v) {
    localStorage.setItem("ct_agent", v);
  },
};
