/**
 * First Contact — Web Frontend Client
 *
 * Tauri migration notes:
 * - Replace WS_URL with Tauri's IPC or a localhost WebSocket spawned by the Tauri sidecar.
 * - Replace localStorage with Tauri's fs or store plugin.
 * - Replace window.open links with Tauri's shell.open().
 * - The rest of the UI code works as-is inside a Tauri webview.
 */

// --- Configuration ---
const WS_URL = "ws://localhost:8765";
const RECONNECT_MIN = 1000;
const RECONNECT_MAX = 30000;
const SCROLL_THRESHOLD = 100;

// --- DOM refs ---
const chatArea = document.getElementById("chatArea");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const modelSelect = document.getElementById("modelSelect");
const newChatBtn = document.getElementById("newChatBtn");
const tokenDisplay = document.getElementById("tokenDisplay");
const accentPicker = document.getElementById("accentPicker");
const connectionDot = document.getElementById("connectionDot");
const reconnectBanner = document.getElementById("reconnectBanner");

// --- State ---
let ws = null;
let reconnectDelay = RECONNECT_MIN;
let currentBubble = null;
let currentRawText = "";
let isStreaming = false;
let userScrolledUp = false;

// --- marked.js configuration ---
marked.setOptions({
    breaks: true,
    gfm: true,
});

// --- WebSocket ---

function connect() {
    ws = new WebSocket(WS_URL);
    setConnectionState("connecting");

    ws.onopen = () => {
        setConnectionState("connected");
        reconnectDelay = RECONNECT_MIN;
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleServerMessage(data);
    };

    ws.onclose = () => {
        setConnectionState("disconnected");
        scheduleReconnect();
    };

    ws.onerror = () => {
        // onclose will fire after this
    };
}

function scheduleReconnect() {
    setTimeout(() => {
        reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX);
        connect();
    }, reconnectDelay);
}

function setConnectionState(state) {
    connectionDot.className = "connection-dot";
    if (state === "connected") {
        connectionDot.classList.add("connected");
        connectionDot.title = "Connected";
        reconnectBanner.classList.remove("visible");
    } else if (state === "connecting") {
        connectionDot.classList.add("connecting");
        connectionDot.title = "Connecting...";
    } else {
        connectionDot.title = "Disconnected";
        reconnectBanner.classList.add("visible");
    }
}

// --- Message Handling ---

function handleServerMessage(data) {
    switch (data.type) {
        case "stream":
            if (!currentBubble) {
                removeTypingIndicator();
                currentBubble = createBubble("assistant");
                currentRawText = "";
            }
            currentRawText += data.content;
            currentBubble.innerHTML = marked.parse(currentRawText);
            autoScroll();
            break;

        case "tool_status":
            updateTypingIndicator(data.content);
            break;

        case "tool_end":
            removeTypingIndicator();
            break;

        case "confirm":
            showConfirmDialog(data.content);
            break;

        case "conversation_list":
            // Handled by index.html's richer UI; no-op here
            break;

        case "file_list":
            // Handled by index.html's sidebar; no-op here
            break;

        case "file_preview_result":
            // Handled by index.html's sidebar; no-op here
            break;

        case "file_download_result":
            // Handled by index.html's sidebar; no-op here
            break;

        case "response":
            // Finalize the current bubble with the complete response
            if (currentBubble && data.content) {
                currentRawText = data.content;
                currentBubble.innerHTML = marked.parse(currentRawText);
            }
            currentBubble = null;
            currentRawText = "";
            removeTypingIndicator();
            setStreaming(false);

            // Update token display
            if (data.cost !== undefined) {
                const parts = [];
                if (data.input_tokens) parts.push(`${data.input_tokens} in`);
                if (data.output_tokens) parts.push(`${data.output_tokens} out`);
                parts.push(`$${data.cost.toFixed(4)}`);
                if (data.session_cost) parts.push(`session: $${data.session_cost.toFixed(4)}`);
                tokenDisplay.textContent = parts.join(" / ");
            }
            autoScroll();
            break;

        case "status":
            showStatus(data.content);
            break;

        case "models": {
            const sel = document.getElementById("modelSelect");
            sel.innerHTML = "";
            const tierOrder = ["sonnet", "haiku", "opus"];
            for (const tier of tierOrder) {
                if (data.models[tier]) {
                    const opt = document.createElement("option");
                    opt.value = tier;
                    opt.textContent = data.models[tier];
                    sel.appendChild(opt);
                }
            }
            if (data.active) {
                for (const [tier, mid] of Object.entries(data.models)) {
                    if (mid === data.active) { sel.value = tier; break; }
                }
            }
            break;
        }

        case "model_set":
            if (data.model) {
                const sel = document.getElementById("modelSelect");
                for (const opt of sel.options) {
                    if (opt.textContent === data.model) { sel.value = opt.value; break; }
                }
                showStatus(`Switched to ${data.model}.`);
            }
            break;

        case "error":
            removeTypingIndicator();
            setStreaming(false);
            currentBubble = null;
            currentRawText = "";
            showStatus(data.content);
            break;
    }
}

// --- UI Helpers ---

function createBubble(role) {
    const el = document.createElement("div");
    el.className = `message ${role}`;
    chatArea.appendChild(el);
    return el;
}

function showTypingIndicator(text) {
    removeTypingIndicator();
    const el = document.createElement("div");
    el.className = "typing-indicator";
    el.id = "typingIndicator";
    el.innerHTML = `
        <div class="typing-dots"><span></span><span></span><span></span></div>
        <span class="typing-text">${escapeHtml(text || "Thinking...")}</span>
    `;
    chatArea.appendChild(el);
    autoScroll();
}

function updateTypingIndicator(text) {
    let el = document.getElementById("typingIndicator");
    if (!el) {
        showTypingIndicator(text);
        return;
    }
    const textEl = el.querySelector(".typing-text");
    if (textEl) textEl.textContent = text;
}

function removeTypingIndicator() {
    const el = document.getElementById("typingIndicator");
    if (el) el.remove();
}

function showStatus(text) {
    const el = document.createElement("div");
    el.style.textAlign = "center";
    el.style.padding = "4px 0";
    el.style.fontSize = "0.75rem";
    el.style.color = "var(--fc-text-dim)";
    el.style.fontStyle = "italic";
    el.style.opacity = "0.7";
    el.textContent = text;
    chatArea.appendChild(el);
    autoScroll();
}

function setStreaming(value) {
    isStreaming = value;
    sendBtn.disabled = value;
    messageInput.disabled = value;
    if (!value) messageInput.focus();
}

function clearChat() {
    chatArea.innerHTML = "";
    tokenDisplay.textContent = "";
    currentBubble = null;
    currentRawText = "";
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// --- Confirmation Dialog ---

function formatConfirmPrompt(prompt) {
    const codeMatch = prompt.match(/\[code\]\n([\s\S]*?)\n\[\/code\]/);
    if (codeMatch) {
        const before = escapeHtml(prompt.substring(0, prompt.indexOf("[code]")).trim());
        const after = escapeHtml(prompt.substring(prompt.indexOf("[/code]") + 7).trim());
        const code = escapeHtml(codeMatch[1]);
        return `${before}<details><summary>Show code</summary><pre style="margin:8px 0;padding:8px;background:#1a1a2e;border-radius:4px;overflow-x:auto;white-space:pre-wrap">${code}</pre></details>${after}`;
    }
    return escapeHtml(prompt);
}

function showConfirmDialog(prompt) {
    removeTypingIndicator();
    const el = document.createElement("div");
    el.className = "message assistant";
    el.id = "confirmDialog";
    el.style.whiteSpace = "pre-wrap";
    el.innerHTML = `<strong>Confirmation required</strong>\n${formatConfirmPrompt(prompt)}\n` +
        `<button onclick="respondConfirm(true)" style="margin-right:8px;cursor:pointer">Approve</button>` +
        `<button onclick="respondConfirm(false)" style="cursor:pointer">Deny</button>`;
    chatArea.appendChild(el);
    autoScroll();
}

function respondConfirm(approved) {
    const dialog = document.getElementById("confirmDialog");
    if (dialog) {
        dialog.innerHTML = `<em>${approved ? "Approved" : "Denied"}</em>`;
        dialog.id = "";
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "confirm_response", approved }));
    }
}

// --- Smart Auto-Scroll ---

chatArea.addEventListener("scroll", () => {
    const distFromBottom = chatArea.scrollHeight - chatArea.scrollTop - chatArea.clientHeight;
    userScrolledUp = distFromBottom > SCROLL_THRESHOLD;
});

function autoScroll() {
    if (!userScrolledUp) {
        chatArea.scrollTop = chatArea.scrollHeight;
    }
}

// --- Send Message ---

function sendMessage() {
    const text = messageInput.value.trim();
    const hasAttachments = pendingAttachments.length > 0;
    if ((!text && !hasAttachments) || isStreaming || !ws || ws.readyState !== WebSocket.OPEN) return;

    // Clear welcome message
    const welcome = chatArea.querySelector(".welcome-message");
    if (welcome) welcome.remove();

    // Show user bubbles for attachments
    for (const f of pendingAttachments) {
        const bubble = createBubble("user");
        bubble.textContent = `[Attached: ${f.name}]`;
    }

    // User bubble for text
    if (text) {
        const bubble = createBubble("user");
        bubble.textContent = text;
    }

    messageInput.value = "";
    autoResizeInput();
    setStreaming(true);
    showTypingIndicator(hasAttachments ? "Processing files..." : "Thinking...");

    const payload = {
        type: "message",
        content: text,
        model: modelSelect.value,
    };
    if (hasAttachments) {
        payload.files = pendingAttachments;
    }
    ws.send(JSON.stringify(payload));

    pendingAttachments = [];
    autoScroll();
}

// --- Input Handling ---

messageInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

messageInput.addEventListener("input", autoResizeInput);

function autoResizeInput() {
    messageInput.style.height = "auto";
    messageInput.style.height = Math.min(messageInput.scrollHeight, 150) + "px";
}

sendBtn.addEventListener("click", sendMessage);

// --- Controls ---

newChatBtn.addEventListener("click", () => {
    if (isStreaming) return;
    clearChat();
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "new_chat" }));
    }
});

modelSelect.addEventListener("change", () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: "set_model",
            model: modelSelect.value,
        }));
    }
});

// --- Accent Color ---

function applyAccent(color) {
    const r = parseInt(color.slice(1, 3), 16);
    const g = parseInt(color.slice(3, 5), 16);
    const b = parseInt(color.slice(5, 7), 16);
    document.documentElement.style.setProperty("--fc-accent", color);
    document.documentElement.style.setProperty("--fc-accent-muted", `rgba(${r}, ${g}, ${b}, 0.5)`);
    document.documentElement.style.setProperty("--fc-accent-40", `rgba(${r}, ${g}, ${b}, 0.4)`);
}

// Load saved accent
const savedAccent = localStorage.getItem("fc-accent");
if (savedAccent) {
    accentPicker.value = savedAccent;
    applyAccent(savedAccent);
}

accentPicker.addEventListener("input", (e) => {
    applyAccent(e.target.value);
    localStorage.setItem("fc-accent", e.target.value);
});

// --- Drag-and-Drop File Attachment (temporary, sent with next message) ---

const ALLOWED_EXTENSIONS = new Set([
    ".txt", ".md", ".py", ".js", ".json", ".csv", ".html", ".css",
    ".yml", ".yaml", ".toml", ".cfg", ".log", ".xml", ".sh", ".bat",
    ".sql", ".r", ".dart", ".pdf", ".docx", ".xlsx",
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
]);

const BINARY_EXTENSIONS = new Set([
    ".pdf", ".docx", ".xlsx",
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
]);

function getExtension(filename) {
    const dot = filename.lastIndexOf(".");
    return dot >= 0 ? filename.slice(dot).toLowerCase() : "";
}

let pendingAttachments = [];

// Target the input area for drag-and-drop (temporary attachments)
const inputArea = messageInput.closest(".input-area") || messageInput.parentElement;

inputArea.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
    inputArea.classList.add("drag-over");
});

inputArea.addEventListener("dragleave", (e) => {
    e.stopPropagation();
    if (!inputArea.contains(e.relatedTarget)) {
        inputArea.classList.remove("drag-over");
    }
});

inputArea.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    inputArea.classList.remove("drag-over");

    const droppedFiles = Array.from(e.dataTransfer.files);
    if (droppedFiles.length) queueAttachments(droppedFiles);
});

function queueAttachments(files) {
    const valid = [];
    const rejected = [];
    for (const file of files) {
        const ext = getExtension(file.name);
        if (ALLOWED_EXTENSIONS.has(ext)) {
            valid.push(file);
        } else {
            rejected.push(file.name);
        }
    }

    if (rejected.length) {
        showStatus(`Skipped unsupported: ${rejected.join(", ")}`);
    }
    if (!valid.length) return;

    for (const file of valid) {
        const reader = new FileReader();
        reader.onload = () => {
            pendingAttachments.push({ name: file.name, contents: reader.result });
            showStatus(`Attached: ${file.name} (will send with next message)`);
        };
        reader.onerror = () => {
            showStatus(`Failed to read: ${file.name}`);
        };
        if (BINARY_EXTENSIONS.has(getExtension(file.name))) {
            reader.readAsDataURL(file);
        } else {
            reader.readAsText(file);
        }
    }
}

// Handle file_upload_result from server
const _origHandler = handleServerMessage;
handleServerMessage = function(data) {
    if (data.type === "file_upload_result") {
        showStatus(data.content);
        return;
    }
    _origHandler(data);
};

// --- Init ---
connect();
