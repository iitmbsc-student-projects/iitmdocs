import { Marked } from "https://cdn.jsdelivr.net/npm/marked@13/+esm";
import { asyncLLM } from "https://cdn.jsdelivr.net/npm/asyncllm@2";
import { html, render } from "https://cdn.jsdelivr.net/npm/lit-html@3/+esm";
import { unsafeHTML } from "https://cdn.jsdelivr.net/npm/lit-html@3/directives/unsafe-html.js";
// Storage with fallback for private browsing: localStorage -> sessionStorage -> cookies -> memory
import { storage } from "https://cdn.jsdelivr.net/npm/local-storage-fallback/+esm";
import { docViewer } from "./doc-viewer.js";

const chatArea = document.getElementById("chat-area");
const chatForm = document.getElementById("chat-form");
const askButton = document.getElementById("ask-button");
const questionInput = document.getElementById("question-input");
const clearChatButton = document.getElementById("clear-chat-button");
const minWordsHint = document.getElementById("min-words-hint");
const usernameInput = document.getElementById("username-input");

const chat = [];
const MIN_WORD_COUNT = 5;
const CONSENT_KEY = "iitm-chatbot-consent";
const WELCOME_MESSAGE = `👋 **Welcome to the IITM BS Degree Program Assistant!**

I can help you with questions about:
- Admission pathways and eligibility
- Qualifier exam preparation and fees
- Course registration steps
- And more!

Please type your question below (minimum 5 words).`;
const SESSION_ID_KEY = "iitm-chatbot-session-id";
const USERNAME_KEY = "iitm-chatbot-username";
// Get parent origin from URL parameter for secure postMessage (set by chatbot.js)
const PARENT_ORIGIN = new URLSearchParams(window.location.search).get("parentOrigin") || window.location.origin;

/**
 * Gets or creates a unique session ID stored in storage (with fallback for private browsing).
 * This persists across page reloads and tabs for the same browser.
 * @returns {string} - The session ID (UUID format)
 */
function getOrCreateSessionId() {
  let sessionId = storage.getItem(SESSION_ID_KEY);
  if (!sessionId) {
    // Generate a UUID v4
    sessionId = crypto.randomUUID();
    storage.setItem(SESSION_ID_KEY, sessionId);
    console.log("[Session] Created new session ID:", sessionId);
  }
  return sessionId;
}

// Initialize session ID on page load
const sessionId = getOrCreateSessionId();

// Initialize username: URL param takes priority, then storage
const urlParams = new URLSearchParams(window.location.search);
const urlUsername = urlParams.get("username");
if (urlUsername) {
  usernameInput.value = urlUsername;
  storage.setItem(USERNAME_KEY, urlUsername);
} else {
  usernameInput.value = storage.getItem(USERNAME_KEY) || "";
}
usernameInput.addEventListener("input", () => {
  storage.setItem(USERNAME_KEY, usernameInput.value);
});

// Feedback categories for the report form
const FEEDBACK_CATEGORIES = [
  { value: "wrong_info", label: "Wrong information" },
  { value: "outdated", label: "Outdated information" },
  { value: "unhelpful", label: "Unhelpful response" },
  { value: "other", label: "Other" },
];

/**
 * Submits feedback to the backend
 * @param {Object} feedbackData - The feedback data to submit
 * @throws {Error} If the request fails or returns non-OK status
 */
async function submitFeedback(feedbackData) {
  const response = await fetch("./feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      program_id: PROGRAM_ID,
      ...feedbackData,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: "Unknown error" }));
    throw new Error(error.error || `HTTP ${response.status}`);
  }
}

/**
 * Counts words in a string (splits by whitespace)
 * @param {string} text - Text to count words in
 * @returns {number} - Number of words
 */
function countWords(text) {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  return trimmed.split(/\s+/).length;
}

/**
 * Updates the ask button state and hint visibility based on word count
 */
function updateInputValidation() {
  const wordCount = countWords(questionInput.value);
  const isValid = wordCount >= MIN_WORD_COUNT;

  askButton.disabled = !isValid;
  minWordsHint.style.display = isValid ? "none" : "block";
}

// Add input listener for real-time validation
questionInput.addEventListener("input", updateInputValidation);
const marked = new Marked();

const DEFAULT_GITHUB_BRANCH_BASE_URL =
  "https://github.com/iitmbsc-student-projects/iitmdocs/blob/main/";
let githubBranchBaseUrl = DEFAULT_GITHUB_BRANCH_BASE_URL;
let runtimePrograms = ["ds", "es", "mg", "ae"];
let runtimeDefaultProgramId = "ds";

try {
  const configResponse = await fetch("./github-config");
  if (configResponse.ok) {
    const runtimeConfig = await configResponse.json();
    if (typeof runtimeConfig.githubBranchBaseUrl === "string") {
      githubBranchBaseUrl = runtimeConfig.githubBranchBaseUrl;
    }
    if (Array.isArray(runtimeConfig.programs) && runtimeConfig.programs.length) {
      runtimePrograms = runtimeConfig.programs;
    }
    if (typeof runtimeConfig.defaultProgramId === "string") {
      runtimeDefaultProgramId = runtimeConfig.defaultProgramId;
    }
  } else {
    console.warn("Runtime config response was not successful; using default URL.");
  }
} catch (error) {
  console.error("Could not load runtime configuration; using default URL:", error);
}

// Which of the four programmes this chat window is for. chatbot.js puts it in the
// iframe URL; opening /qa?program_id=es directly works the same way. The valid ids
// come from the server (programs.py) so they are not repeated here, and anything
// unrecognised falls back to the default programme rather than failing to load.
const PROGRAM_ID = (() => {
  const requested = (urlParams.get("program_id") || "").trim().toLowerCase();
  return runtimePrograms.includes(requested) ? requested : runtimeDefaultProgramId;
})();

githubBranchBaseUrl = githubBranchBaseUrl.replace(/\/?$/, "/");
const PROGRAM_CONTACT_DETAILS_URL = `${githubBranchBaseUrl}docs/program-contact-details.md`;

// Configure marked to open links in new window
marked.use({
  renderer: {
    link(href, title, text) {
      const titleAttr = title ? ` title="${title}"` : "";
      if (href === PROGRAM_CONTACT_DETAILS_URL) {
        return `<a href="${href}"${titleAttr} class="ref-doc-link" data-name="program-contact-details">${text}</a>`;
      }
      return `<a href="${href}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`;
    }
  }
});
const HISTORY_KEY = `iitm-chatbot-history-${PROGRAM_ID}`;

/**
 * Post-processes HTML to make "Did you mean?" FAQ suggestions clickable.
 * Detects the pattern and converts list items to clickable buttons.
 * @param {string} html - The HTML string from marked.parse()
 * @returns {string} - Processed HTML with clickable suggestions
 */
function processFAQSuggestions(html) {
  const didYouMeanLabels = new Set([
    "Did you mean:",
    "क्या आपका मतलब था:",
    "நீங்கள் கருதுவது:",
    "Kya aap ye poochna chahte the:",
  ]);

  const template = document.createElement("template");
  template.innerHTML = html;

  const paragraphs = [...template.content.querySelectorAll("p")];
  for (const paragraph of paragraphs) {
    const label = paragraph.textContent.trim();
    if (!didYouMeanLabels.has(label)) continue;

    const list = paragraph.nextElementSibling;
    if (!list || list.tagName !== "OL") continue;

    const container = document.createElement("div");
    container.className = "faq-suggestions";
    container.append(paragraph.cloneNode(true));

    for (const item of list.querySelectorAll("li")) {
      const rawText = item.textContent.trim();
      const faqIdMatch = rawText.match(/\[FAQID:(\d+)\]/);
      const displayText = rawText.replace(/\s*\[FAQID:\d+\]/, "").trim();
      if (!displayText) continue;

      const button = document.createElement("button");
      button.type = "button";
      button.className = "faq-suggestion";
      button.dataset.question = displayText;
      if (faqIdMatch) button.dataset.faqId = faqIdMatch[1];
      button.textContent = displayText;
      container.append(button);
    }

    paragraph.replaceWith(container);
    list.remove();
  }

  return template.innerHTML;
}
const MAX_HISTORY_PAIRS = 5;
let requestCounter = 0; // Track requests to prevent race conditions
const TYPING_SPEED_MS = 15; // Milliseconds per character for typing effect

/**
 * Animates typing effect for a chat message
 * @param {Object} msg - The chat message object
 * @param {string} fullContent - The complete content to type out
 * @param {Function} onUpdate - Callback to trigger redraw
 * @returns {Promise} - Resolves when typing is complete
 */
function animateTyping(msg, fullContent, onUpdate) {
  return new Promise((resolve) => {
    let charIndex = 0;
    const totalChars = fullContent.length;

    function typeNextChunk() {
      // Type multiple characters per frame for smoother feel
      const charsPerFrame = 3;
      charIndex = Math.min(charIndex + charsPerFrame, totalChars);
      msg.content = fullContent.slice(0, charIndex);
      onUpdate();

      if (charIndex < totalChars) {
        setTimeout(typeNextChunk, TYPING_SPEED_MS);
      } else {
        resolve();
      }
    }

    typeNextChunk();
  });
}

/**
 * Loads conversation history from sessionStorage
 * @returns {Array} Array of message objects with role and content
 */
function loadHistoryFromStorage() {
  try {
    const stored = sessionStorage.getItem(HISTORY_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch (e) {
    console.error("Failed to load history from sessionStorage:", e);
    return [];
  }
}

/**
 * Saves conversation history to sessionStorage
 * @param {Array} history - Array of message objects to save
 */
function saveHistoryToStorage(history) {
  try {
    sessionStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  } catch (e) {
    console.error("Failed to save history to sessionStorage:", e);
  }
}

/**
 * Builds conversation history from completed chat messages
 * Only includes last MAX_HISTORY_PAIRS Q&A pairs
 * Excludes rejected responses (fact check failed, prompt injection)
 * @returns {Array} Array of message objects with role and content
 */
function buildConversationHistory() {
  // Build history from last N Q&A pairs (excluding current incomplete exchange and rejected)
  const history = [];
  const completedChats = chat.filter((msg) => msg.content && !msg.rejected); // Only completed, non-rejected Q&A pairs
  const recentChats = completedChats.slice(-MAX_HISTORY_PAIRS);

  for (const msg of recentChats) {
    history.push({ role: "user", content: msg.q });
    history.push({ role: "assistant", content: msg.content });
  }

  return history;
}

// Auto-scroll state - must be declared before redraw() is called
let autoScroll = true;
chatArea.addEventListener("scroll", () => {
  const atBottom = chatArea.scrollHeight - chatArea.scrollTop - chatArea.clientHeight < 10;
  autoScroll = atBottom;
});

// Initialize chat from sessionStorage on page load
const storedHistory = loadHistoryFromStorage();
if (storedHistory.length > 0) {
  // Rebuild chat array from stored history
  for (let i = 0; i < storedHistory.length; i += 2) {
    if (storedHistory[i]?.role === "user" && storedHistory[i + 1]?.role === "assistant") {
      chat.push({
        q: storedHistory[i].content,
        content: storedHistory[i + 1].content,
      });
    }
  }
}
// Always call redraw - shows welcome message if empty, or restored conversation
redraw();
if (chat.length > 0) {
  chatArea.scrollTop = chatArea.scrollHeight;
}

function redraw() {
  // Show welcome message if chat is empty
  if (chat.length === 0) {
    render(
      html`<div class="my-3">${unsafeHTML(marked.parse(WELCOME_MESSAGE))}</div>`,
      chatArea,
    );
    return;
  }

  render(
    chat.map(
      ({ q, content, tools, messageId, feedback, showReportForm }) => html`
        <div class="bg-light border rounded p-2">${q}</div>
        <div class="my-3">
          ${content ? unsafeHTML(processFAQSuggestions(marked.parse(content))) : html`<span class="ms-4 spinner-border"></span>`}
        </div>
        ${tools
          ? html`<details class="my-3 px-2" open>
              <summary>References</summary>
              <ul class="list-unstyled ms-3 py-1">
                ${tools?.map?.(({ args }) => {
                  const { name, link } = JSON.parse(args);
                  return html`<li><a href="${link}" class="ref-doc-link" data-name="${name}">${name}</a></li>`;
                })}
              </ul>
            </details>`
          : ""}
        ${content && messageId
          ? html`
              ${feedback === "submitted"
                ? html`<div class="feedback-thanks"><i class="bi bi-check-circle"></i> Thanks for your feedback!</div>`
                : html`
                    <div class="feedback-buttons">
                      <button
                        class="feedback-btn ${feedback === "up" ? "active-up" : ""}"
                        title="Helpful"
                        @click=${() => handleThumbsFeedback(messageId, "up", q, content)}
                      >
                        <i class="bi bi-hand-thumbs-up"></i>
                      </button>
                      <button
                        class="feedback-btn ${feedback === "down" ? "active-down" : ""}"
                        title="Not helpful"
                        @click=${() => handleThumbsFeedback(messageId, "down", q, content)}
                      >
                        <i class="bi bi-hand-thumbs-down"></i>
                      </button>
                      <button
                        class="feedback-btn report"
                        title="Report incorrect answer"
                        @click=${() => toggleReportForm(messageId)}
                      >
                        <i class="bi bi-flag"></i> Report
                      </button>
                    </div>
                    ${showReportForm
                      ? html`
                          <div class="feedback-form">
                            <select id="feedback-category-${messageId}">
                              <option value="">Select issue type...</option>
                              ${FEEDBACK_CATEGORIES.map(
                                (cat) => html`<option value="${cat.value}">${cat.label}</option>`,
                              )}
                            </select>
                            <textarea
                              id="feedback-text-${messageId}"
                              placeholder="Optional: Tell us more about the issue..."
                              maxlength="1000"
                            ></textarea>
                            <div class="feedback-form-buttons">
                              <button class="btn btn-sm btn-outline-secondary" @click=${() => toggleReportForm(messageId)}>
                                Cancel
                              </button>
                              <button
                                class="btn btn-sm btn-warning"
                                @click=${() => handleReportSubmit(messageId, q, content)}
                              >
                                Submit Report
                              </button>
                            </div>
                          </div>
                        `
                      : ""}
                  `}
            `
          : ""}
      `,
    ),
    chatArea,
  );
  if (autoScroll) chatArea.scrollTop = chatArea.scrollHeight;
}

/**
 * Handles thumbs up/down feedback
 * Includes race condition protection and error handling
 */
async function handleThumbsFeedback(messageId, type, question, response) {
  const msg = chat.find((m) => m.messageId === messageId);
  if (!msg) return;

  // Race condition protection: prevent duplicate submissions
  if (msg.feedback && msg.feedback !== "error") return;

  const previousFeedback = msg.feedback;
  msg.feedback = type;
  redraw();

  try {
    await submitFeedback({
      message_id: messageId,
      question,
      response,
      feedback_type: type,
      feedback_category: null,
      feedback_text: null,
    });
  } catch (error) {
    // Reset feedback state on error
    msg.feedback = previousFeedback || "error";
    redraw();
    console.error("Failed to submit feedback:", error);
  }
}

/**
 * Toggles the report form visibility
 */
function toggleReportForm(messageId) {
  const msg = chat.find((m) => m.messageId === messageId);
  if (msg) {
    msg.showReportForm = !msg.showReportForm;
    redraw();
  }
}

/**
 * Handles report form submission
 * Includes error handling and submission state management
 */
async function handleReportSubmit(messageId, question, response) {
  const categorySelect = document.getElementById(`feedback-category-${messageId}`);
  const textArea = document.getElementById(`feedback-text-${messageId}`);
  const category = categorySelect?.value || null;
  const text = textArea?.value?.trim() || null;

  const msg = chat.find((m) => m.messageId === messageId);
  if (!msg) return;

  // Prevent duplicate report submissions
  if (msg.feedback === "submitted") return;

  msg.feedback = "submitted";
  msg.showReportForm = false;
  redraw();

  try {
    await submitFeedback({
      message_id: messageId,
      question,
      response,
      feedback_type: "report",
      feedback_category: category,
      feedback_text: text,
    });
  } catch (error) {
    // Reset to allow retry on error
    msg.feedback = "error";
    msg.showReportForm = true;
    redraw();
    console.error("Failed to submit report:", error);
  }
}

/**
 * Handles asking a question and streaming the response
 * Prevents race conditions by tracking request order
 * @param {Event} e - Submit event from the form
 * @param {string|number} faqId - Optional FAQ id for direct lookup (skips LLM)
 */
async function askQuestion(e, faqId = null) {
  if (e) e.preventDefault();

  const q = questionInput.value.trim();
  // Direct FAQ suggestions may be short (for example, "Fees?"). The FAQ id
  // identifies an exact database row, so the normal minimum-word rule does
  // not apply to that lookup. Normal user questions still require five words.
  if (!q || (!faqId && countWords(q) < MIN_WORD_COUNT)) return;

  questionInput.value = "";
  askButton.disabled = true;
  minWordsHint.style.display = "block"; // Show hint again after clearing input
  askButton.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  // Create unique message ID for feedback tracking
  const messageId = crypto.randomUUID();
  chat.push({ q, messageId, feedback: null, showReportForm: false });
  redraw();

  // Track this request to prevent race conditions
  const currentRequest = ++requestCounter;

  // Build conversation history from previous exchanges (before current question)
  const history = buildConversationHistory();

  try {
    let fullContent = "";
    let otherData = {};

    const requestBody = { q, ndocs: 2, history, session_id: sessionId, message_id: messageId, program_id: PROGRAM_ID, username: usernameInput.value || undefined };
    if (faqId) {
      requestBody.faq_id = Number(faqId);
    }

    // Collect the full response
    for await (const event of asyncLLM("./answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    })) {
      if (event.content) {
        fullContent = event.content;
      }
      // Collect other data like tools
      const { content, ...rest } = event;
      Object.assign(otherData, rest);
    }

    // Apply non-content data immediately
    Object.assign(chat.at(-1), otherData);

    // Animate the typing effect
    if (fullContent) {
      await animateTyping(chat.at(-1), fullContent, redraw);
    }

    // Only save history if this is still the most recent request and not rejected
    // This prevents out-of-order saves if multiple requests were somehow triggered
    // Rejected responses (fact check failed, prompt injection) should not pollute history
    if (currentRequest === requestCounter && !otherData.rejected) {
      saveHistoryToStorage(buildConversationHistory());
    }
  } finally {
    askButton.innerHTML = "Ask";
    updateInputValidation(); // Re-check validation state after response
  }
}
questionInput.focus();

chatForm.addEventListener("submit", askQuestion);

// Event delegation for FAQ suggestion clicks
chatArea.addEventListener("click", function (e) {
  const suggestionBtn = e.target.closest(".faq-suggestion");
  if (suggestionBtn) {
    const question = suggestionBtn.dataset.question;
    const faqId = suggestionBtn.dataset.faqId;
    if (question) {
      // Set the question in the input
      questionInput.value = question;
      // Update validation (will enable the ask button)
      updateInputValidation();
      if (faqId) {
        askQuestion(null, faqId);
      } else {
        // If no FAQ id is present, treat the click as a normal question submission.
        askQuestion(null);
      }
      // Smooth scroll to bottom
      chatArea.scrollTo({ top: chatArea.scrollHeight, behavior: 'smooth' });
    }
  }
});

clearChatButton.addEventListener("click", function () {
  chat.length = 0;
  sessionStorage.removeItem(HISTORY_KEY);
  redraw();
});

// Fullscreen toggle functionality
const fullscreenButton = document.getElementById("fullscreen-button");
const fullscreenIcon = document.getElementById("fullscreen-icon");
let isFullscreen = false;

fullscreenButton.addEventListener("click", function () {
  isFullscreen = !isFullscreen;
  fullscreenIcon.className = isFullscreen ? "bi bi-fullscreen-exit" : "bi bi-fullscreen";
  // Send message to parent window to toggle fullscreen
  // Use explicit parent origin passed via URL parameter for security
  window.parent.postMessage({ type: "toggle-fullscreen", isFullscreen }, PARENT_ORIGIN);
});

// Close chatbot button functionality
const closeChatbotButton = document.getElementById("close-chatbot-button");
closeChatbotButton.addEventListener("click", function () {
  // If fullscreen is active, exit it first
  if (isFullscreen) {
    isFullscreen = false;
    fullscreenIcon.className = "bi bi-fullscreen";
    window.parent.postMessage({ type: "toggle-fullscreen", isFullscreen: false }, PARENT_ORIGIN);
  }
  // Send message to parent window to close the chatbot
  window.parent.postMessage({ type: "close-chatbot" }, PARENT_ORIGIN);
});

// Consent overlay functionality
const consentOverlay = document.getElementById("consent-overlay");
const consentButton = document.getElementById("consent-button");

function hasUserConsent() {
  return storage.getItem(CONSENT_KEY) === "true";
}

function hideConsentOverlay() {
  consentOverlay.classList.add("hidden");
  questionInput.disabled = false;
  questionInput.focus();
}

function showConsentOverlay() {
  consentOverlay.classList.remove("hidden");
  questionInput.disabled = true;
}

// Check consent on page load
if (hasUserConsent()) {
  hideConsentOverlay();
} else {
  showConsentOverlay();
}

// Handle consent button click
consentButton.addEventListener("click", function () {
  storage.setItem(CONSENT_KEY, "true");
  hideConsentOverlay();
});

// Initialize document viewer for reference links
docViewer.init();
