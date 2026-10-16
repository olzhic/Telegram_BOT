const messages = document.querySelector("#messages");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message");
const actions = document.querySelector("#actions");
const sessionStorageKey = "adal-navigator-session";
const sessionId = localStorage.getItem(sessionStorageKey) ?? crypto.randomUUID();
localStorage.setItem(sessionStorageKey, sessionId);
let correcting = false;

class ApiError extends Error {}

function addMessage(value, kind) {
  const article = document.createElement("article");
  article.className = `message ${kind}`;
  article.textContent = value;
  messages.append(article);
  messages.scrollTop = messages.scrollHeight;
  return article;
}

async function send(message, action = "message") {
  let response;
  try {
    response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message, action }),
    });
  } catch {
    throw new ApiError(localizedApiError(503, message));
  }
  let result;
  try {
    result = await response.json();
  } catch {
    throw new ApiError(localizedApiError(response.status, message));
  }
  if (!response.ok) {
    const diagnostics = result.diagnostics;
    if (diagnostics) {
      const requestId = diagnostics.request_id ? `; request ID: ${diagnostics.request_id}` : "";
      throw new ApiError(
        `${result.detail ?? "API error"} (HTTP ${response.status}; stage: ${diagnostics.stage}; error: ${diagnostics.error_type}${requestId})`
      );
    }
    throw new ApiError(result.detail ?? localizedApiError(response.status, message));
  }
  if (result.status === "error") {
    throw new ApiError(result.reply);
  }
  const reply = addMessage(result.reply, "bot");
  for (const citation of result.citations ?? []) {
    const link = document.createElement("a");
    let url;
    try {
      url = new URL(citation.url);
    } catch {
      continue;
    }
    if (url.protocol === "https:" || url.protocol === "http:") {
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = citation.title;
      reply.append(document.createElement("br"), link);
    }
  }
  actions.hidden = result.status !== "confirmation";
  correcting = false;
}

function localizedApiError(status, message) {
  const kazakhLetters = /[әғқңөұүһіӘҒҚҢӨҰҮҺІ]/;
  if (status >= 500) {
    return kazakhLetters.test(message)
      ? "Қызмет уақытша қолжетімсіз. Кейінірек қайталап көріңіз."
      : "Сервис временно недоступен. Пожалуйста, попробуйте позже.";
  }
  return kazakhLetters.test(message)
    ? "Сұрауды өңдеу мүмкін болмады. Кейінірек қайталап көріңіз."
    : "Не удалось обработать запрос. Попробуйте позже.";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = input.value.trim();
  if (!value) return;
  addMessage(value, "user");
  input.value = "";
  try {
    await send(value, correcting ? "correct" : "message");
  } catch (error) {
    addMessage(error.message, "bot");
  }
});

document.querySelector("#confirm").addEventListener("click", async () => {
  actions.hidden = true;
  try {
    await send("", "confirm");
  } catch (error) {
    addMessage(error.message, "bot");
  }
});

document.querySelector("#correct").addEventListener("click", () => {
  correcting = true;
  actions.hidden = true;
  input.placeholder = "Опишите исправленный вариант / Дұрыс нұсқасын жазыңыз";
  input.focus();
});

document.querySelector("#reset").addEventListener("click", async () => {
  try {
    await send("", "reset");
  } catch (error) {
    addMessage(error.message, "bot");
  }
});
