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
    el.className = "message assistant";
    el.style.fontStyle = "italic";
    el.style.color = "var(--fc-text-dim)";
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
    if (!text || isStreaming || !ws || ws.readyState !== WebSocket.OPEN) return;

    // Clear welcome message
    const welcome = chatArea.querySelector(".welcome-message");
    if (welcome) welcome.remove();

    // User bubble
    const bubble = createBubble("user");
    bubble.textContent = text;

    messageInput.value = "";
    autoResizeInput();
    setStreaming(true);
    showTypingIndicator("Thinking...");

    ws.send(JSON.stringify({
        type: "message",
        content: text,
        model: modelSelect.value,
    }));

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

// --- Drag-and-Drop File Upload ---

const ALLOWED_EXTENSIONS = new Set([
    ".txt", ".md", ".py", ".js", ".json", ".csv", ".html", ".css",
    ".yml", ".yaml", ".toml", ".cfg", ".log", ".xml", ".sh", ".bat",
    ".sql", ".r", ".dart", ".pdf", ".docx", ".xlsx",
]);

const BINARY_EXTENSIONS = new Set([".pdf", ".docx", ".xlsx"]);

function getExtension(filename) {
    const dot = filename.lastIndexOf(".");
    return dot >= 0 ? filename.slice(dot).toLowerCase() : "";
}

chatArea.addEventListener("dragover", (e) => {
    e.preventDefault();
    chatArea.closest("main").classList.add("drag-over");
});

chatArea.addEventListener("dragleave", (e) => {
    // Only remove if we're leaving the main area entirely
    if (!e.relatedTarget || !chatArea.closest("main").contains(e.relatedTarget)) {
        chatArea.closest("main").classList.remove("drag-over");
    }
});

chatArea.addEventListener("drop", (e) => {
    e.preventDefault();
    chatArea.closest("main").classList.remove("drag-over");

    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    const droppedFiles = Array.from(e.dataTransfer.files);
    if (!droppedFiles.length) return;

    // Filter valid files
    const valid = [];
    const rejected = [];
    for (const file of droppedFiles) {
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

    // Show user bubble for each file
    for (const file of valid) {
        const bubble = createBubble("user");
        bubble.textContent = `[File: ${file.name}]`;
    }

    // Read all files and send as chat attachment (temporary, not persisted)
    let pending = valid.length;
    const fileData = [];

    for (const file of valid) {
        const reader = new FileReader();
        reader.onload = () => {
            fileData.push({ name: file.name, contents: reader.result });
            pending--;
            if (pending === 0) {
                // Clear welcome message
                const welcome = chatArea.querySelector(".welcome-message");
                if (welcome) welcome.remove();

                // Show user bubble for attached files
                for (const f of fileData) {
                    const bubble = createBubble("user");
                    bubble.textContent = `[Attached: ${f.name}]`;
                }

                const text = messageInput.value.trim();
                if (text) {
                    const bubble = createBubble("user");
                    bubble.textContent = text;
                }

                setStreaming(true);
                showTypingIndicator("Processing files...");

                ws.send(JSON.stringify({
                    type: "message",
                    content: text,
                    model: modelSelect.value,
                    files: fileData,
                }));

                messageInput.value = "";
                autoResizeInput();
                autoScroll();
            }
        };
        reader.onerror = () => {
            showStatus(`Failed to read: ${file.name}`);
            pending--;
        };
        if (BINARY_EXTENSIONS.has(getExtension(file.name))) {
            reader.readAsDataURL(file);
        } else {
            reader.readAsText(file);
        }
    }
});

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
