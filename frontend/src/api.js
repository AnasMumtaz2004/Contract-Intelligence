// Change this if your backend runs on another address
const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// A document sent by the backend looks like this:
// { id, contract_id, vendor_name, file_name, document_type, status,
//   error_message, page_count, chunk_count, created_at }
//
// A message looks like this:
// { id, role, content, status, citations: [{ number, chunk_id, file_name,
//   section_path, page_number, content }], created_at }

/** Read the login token from the browser. */
export function getToken() {
  return localStorage.getItem("token");
}

/** Remember the login token in the browser. */
export function saveToken(token) {
  localStorage.setItem("token", token);
}

/** Forget the login token (log out). */
export function clearToken() {
  localStorage.removeItem("token");
}

/** Read the error message from a failed response. */
async function readErrorMessage(response) {
  let message = "Something went wrong";

  // The error body is not always JSON, so this try/catch is needed
  try {
    const body = await response.json();
    if (typeof body.detail === "string") {
      message = body.detail;
    }
  } catch {
    message = "Server error (" + response.status + ")";
  }

  // An expired token means we must log in again
  if (response.status === 401 && getToken() !== null) {
    clearToken();
    window.location.href = "/login";
  }

  return message;
}

/** Send a request to the backend and return the JSON answer. */
async function request(path, options = {}) {
  const headers = new Headers(options.headers);

  // Add the token to every request when we are logged in
  const token = getToken();
  if (token !== null) {
    headers.set("Authorization", "Bearer " + token);
  }

  const response = await fetch(API_URL + path, { ...options, headers });

  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new Error(message);
  }

  return response.json();
}

/** Create a new account. */
export async function registerUser(email, password) {
  await request("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

/** Log in and save the token. */
export async function loginUser(email, password) {
  const data = await request("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  saveToken(data.access_token);
}

/** Get all documents of the logged-in user. */
export async function getDocuments() {
  return request("/documents");
}

/** Get one document (used to follow the processing status). */
export async function getDocument(id) {
  return request("/documents/" + id);
}

/** Upload a PDF with its vendor name and type. */
export async function uploadDocument(file, vendorName, documentType) {
  // FormData lets us send a file. The browser sets the content type for us.
  const formData = new FormData();
  formData.append("file", file);
  formData.append("vendor_name", vendorName);
  formData.append("document_type", documentType);

  return request("/documents/upload", { method: "POST", body: formData });
}

/** Delete a document. */
export async function deleteDocument(id) {
  await request("/documents/" + id, { method: "DELETE" });
}

/** Get all contracts (one per vendor) of the logged-in user. */
export async function getContracts() {
  return request("/contracts");
}

/** Get all conversations of the logged-in user. */
export async function getConversations() {
  return request("/chat/conversations");
}

/** Start a conversation. A contractId of null means all contracts. */
export async function createConversation(title, contractId) {
  return request("/chat/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title, contract_id: contractId }),
  });
}

/** Get the messages of a conversation. */
export async function getMessages(conversationId) {
  return request("/chat/conversations/" + conversationId + "/messages");
}

/** Get a chunk and its full section for the citation viewer. */
export async function getChunkDetail(chunkId) {
  return request("/chat/chunks/" + chunkId);
}

/** Turn one block of event text into a name and a data object. */
function parseEvent(eventText) {
  let eventName = "message";
  let dataText = "";

  const lines = eventText.split("\n");
  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    }
    if (line.startsWith("data:")) {
      dataText = line.slice(5).trim();
    }
  }

  let data = {};
  if (dataText !== "") {
    data = JSON.parse(dataText);
  }
  return { eventName, data };
}

/** Ask a question and call onEvent(name, data) for each event the server sends. */
export async function askQuestion(conversationId, question, onEvent) {
  // EventSource cannot send a POST with a token, so we read the stream with fetch
  const response = await fetch(API_URL + "/chat/conversations/" + conversationId + "/ask", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + getToken(),
    },
    body: JSON.stringify({ question: question }),
  });

  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new Error(message);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });

    // Events are separated by a blank line. The last part may be unfinished, so we keep it.
    const parts = buffer.split("\n\n");
    buffer = parts.pop();

    for (const part of parts) {
      if (part.trim() === "") {
        continue;
      }
      const event = parseEvent(part);
      onEvent(event.eventName, event.data);
    }
  }
}


/** Ask the LLM to guess the vendor, type and date of a processed document. */
export async function getSuggestions(documentId) {
  return request("/documents/" + documentId + "/suggestions");
}

/** Save the vendor, type, date and parent document that the user confirmed. */
export async function updateMetadata(documentId, metadata) {
  return request("/documents/" + documentId + "/metadata", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(metadata),
  });
}

/** Send a thumbs up (1) or thumbs down (-1) for an answer. */
export async function sendFeedback(messageId, rating) {
  return request("/chat/messages/" + messageId + "/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating: rating }),
  });
}

/** Let a blocked document through. Its instruction-like sentences are still removed. */
export async function releaseDocument(id) {
  return request("/documents/" + id + "/release", { method: "POST" });
}

/** Get the contract that follow-up questions of a conversation focus on. */
export async function getFocus(conversationId) {
  return request("/chat/conversations/" + conversationId + "/focus");
}

/** Stop focusing on one contract. */
export async function clearFocus(conversationId) {
  return request("/chat/conversations/" + conversationId + "/focus", { method: "DELETE" });
}