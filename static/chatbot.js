export const chatbotCSS = /* css */ `
/* Chatbot CSS Variables */
:root {
  --chatbot-primary: #2563eb;
  --chatbot-primary-hover: #1d4ed8;
  --chatbot-text-on-primary: #ffffff;
  --chatbot-offset-right: 90px;
  --chatbot-offset-bottom: 30px;
}

/* Chatbot styles */
.chatbot-toggler {
  z-index:1000;
  position: fixed;
  bottom: var(--chatbot-offset-bottom);
  right: var(--chatbot-offset-right);
  outline: none;
  border: 2px solid rgba(255,255,255,0.9);
  height: 48px;
  padding: 0 20px;
  display: flex;
  cursor: pointer;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 24px;
  background: var(--chatbot-primary);
  box-shadow: 0 0 0 3px rgba(255,255,255,0.8), 0 4px 16px rgba(0,0,0,0.3), 0 0 20px rgba(255,255,255,0.3);
  transition: all 0.2s ease;
}

.chatbot-toggler:hover {
  transform: scale(1.05);
  box-shadow: 0 0 0 4px rgba(255,255,255,0.9), 0 6px 20px rgba(0,0,0,0.4), 0 0 25px rgba(255,255,255,0.4);
}

@keyframes chatbot-pulse {
  0% { transform: scale(1); }
  15% { transform: scale(1.1); }
  30% { transform: scale(1); }
  45% { transform: scale(1.08); }
  60% { transform: scale(1); }
  100% { transform: scale(1); }
}

.chatbot-toggler.pulse {
  animation: chatbot-pulse 0.6s ease-in-out;
}

.chatbot-toggler-open {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #fff;
}

.chatbot-toggler-open span.material-symbols-rounded {
  font-size: 22px;
}

.chatbot-toggler-label {
  font-size: 14px;
  font-weight: 500;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  white-space: nowrap;
}

.chatbot-toggler .chatbot-toggler-close {
  color: #fff;
  display: none !important;
  font-size: 24px;
}

body.show-chatbot .chatbot-toggler .chatbot-toggler-close {
  display: block !important;
}

body.show-chatbot .chatbot-toggler {
  padding: 0;
  width: 48px;
  border-radius: 50%;
}

body.show-chatbot .chatbot-toggler-open {
  display: none;
}

.chatbot {
  z-index:1000;
  position: fixed;
  right: var(--chatbot-offset-right);
  bottom: calc(var(--chatbot-offset-bottom) + 60px);
  width: 420px;
  height: 70vh;
  max-height: 600px;
  min-height: 400px;
  background: #fff;
  border: 2px solid var(--chatbot-primary);
  border-radius: 15px;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
  transform: scale(0.5);
  transform-origin: bottom right;
  box-shadow: 0 0 128px 0 rgba(0, 0, 0, 0.1),
              0 32px 64px -48px rgba(0, 0, 0, 0.5);
  transition: all 0.1s ease;
}

body.show-chatbot .chatbot {
  opacity: 1;
  pointer-events: auto;
  transform: scale(1);
}

.chatbot .chatbox {
  overflow-y: hidden;
  height: 100%;
  padding: 0;
}

.chatbot :where(.chatbox, textarea)::-webkit-scrollbar {
  width: 6px;
}

.chatbot :where(.chatbox, textarea)::-webkit-scrollbar-track {
  background: #fff;
  border-radius: 25px;
}

.chatbot :where(.chatbox, textarea)::-webkit-scrollbar-thumb {
  background: #ccc;
  border-radius: 25px;
}

@media (max-width: 490px) {
  .chatbot-toggler {
    right: var(--chatbot-offset-right);
    bottom: var(--chatbot-offset-bottom);
    padding: 0;
    width: 48px;
    border-radius: 50%;
  }

  .chatbot-toggler-label {
    display: none;
  }

  .chatbot {
    right: 0;
    bottom: 0;
    height: 100%;
    border-radius: 0;
    width: 100%;
  }

  .chatbot .chatbox {
    height: 100%;
    padding: 0;
  }
}

/* Fullscreen state */
body.chatbot-fullscreen::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 999;
}

body.chatbot-fullscreen .chatbot {
  width: 95vw;
  height: calc(100vh - 100px);
  max-height: none;
  right: 2.5vw;
  bottom: 90px;
  border-radius: 10px;
}
`;

export function addChatbotStyles() {
  const styleId = "chatbot-styles";
  if (document.getElementById(styleId)) return;
  const style = document.createElement("style");
  style.id = styleId;
  style.innerHTML = chatbotCSS;
  document.head.appendChild(style);
}

/**
 * Finds the script tag that loaded chatbot.js
 * @returns {HTMLScriptElement|null}
 */
function getChatbotScript() {
  const scripts = document.getElementsByTagName('script');
  for (const script of scripts) {
    if (script.src && script.src.includes('chatbot.js')) {
      return script;
    }
  }
  return null;
}

/**
 * Gets the base URL of where chatbot.js was loaded from.
 * This allows the chatbot to be embedded on any site while loading resources from the correct origin.
 * @returns {string} Base URL (e.g., "https://chatbot.example.com/")
 */
function getChatbotBaseUrl() {
  const script = getChatbotScript();
  if (script) {
    return script.src.replace(/chatbot\.js.*$/, '');
  }
  // Fallback to current origin if script not found
  return window.location.origin + '/';
}

/**
 * Gets position offsets from script tag data attributes.
 * Usage: <script src="chatbot.js" data-offset-right="90" data-offset-bottom="30"></script>
 * @returns {{ right: string, bottom: string }}
 */
function getPositionOffsets() {
  const script = getChatbotScript();
  const defaults = { right: '90px', bottom: '30px' };

  if (!script) return defaults;

  const right = script.dataset.offsetRight;
  const bottom = script.dataset.offsetBottom;

  return {
    right: right ? `${right}px` : defaults.right,
    bottom: bottom ? `${bottom}px` : defaults.bottom
  };
}

/**
 * Which of the four programmes this embed is for.
 * The host page picks it on the script tag:
 *   <script src=".../chatbot.js" data-program-id="es"></script>
 * Missing means "ds", so existing embeds keep working unchanged.
 */
function getProgramId() {
  const script = getChatbotScript();
  return script?.dataset.programId || "ds";
}

export function getChatbotHTML(baseUrl, parentOrigin, programId = "ds") {
  // Pass parent origin to iframe so it can use explicit targetOrigin in postMessage
  const params = new URLSearchParams();
  if (parentOrigin) params.set("parentOrigin", parentOrigin);
  params.set("program_id", programId);
  const iframeSrc = `${baseUrl}qa.html?${params.toString()}`;
  return /* html */ `
  <button class="chatbot-toggler">
    <span class="chatbot-toggler-open">
      <span class="material-symbols-rounded">contact_support</span>
      <span class="chatbot-toggler-label">Need Help?</span>
    </span>
    <span class="material-symbols-outlined chatbot-toggler-close">close</span>
  </button>
  <div class="chatbot">
    <div class="chatbox">
      <iframe src="${iframeSrc}" style="width: 100%; height: 100%; border: none;"></iframe>
    </div>
  </div>
`;
}

export const googleIconsHTML = /* html */ `
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@48,400,0,0">
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@48,400,1,0">
`;

export function initChatbot() {
  addChatbotStyles();

  // Apply position offsets from script tag data attributes
  const offsets = getPositionOffsets();
  document.documentElement.style.setProperty('--chatbot-offset-right', offsets.right);
  document.documentElement.style.setProperty('--chatbot-offset-bottom', offsets.bottom);

  const baseUrl = getChatbotBaseUrl();
  const parentOrigin = window.location.origin;
  const programId = getProgramId();
  document.body.insertAdjacentHTML("beforeend", getChatbotHTML(baseUrl, parentOrigin, programId));

  const chatbotToggler = document.querySelector(".chatbot-toggler");

  // Pulse animation every 15 seconds until user clicks
  let pulseInterval = null;

  function triggerPulse() {
    chatbotToggler.classList.add('pulse');
    // Remove class after animation completes to allow re-triggering
    setTimeout(() => chatbotToggler.classList.remove('pulse'), 600);
  }

  function startPulseAnimation() {
    // Initial pulse after 3 seconds, then every 3 seconds
    pulseInterval = setInterval(triggerPulse, 3000);
  }

  function stopPulseAnimation() {
    if (pulseInterval) {
      clearInterval(pulseInterval);
      pulseInterval = null;
    }
  }

  chatbotToggler.addEventListener("click", () => {
    stopPulseAnimation();
    document.body.classList.toggle("show-chatbot");
  });

  // Start pulse animation
  startPulseAnimation();

  // Determine the expected origin for postMessage validation
  // If embedded cross-origin, accept messages from the chatbot's origin
  const chatbotOrigin = new URL(baseUrl).origin;

  // Listen for fullscreen toggle messages from the iframe
  window.addEventListener("message", (event) => {
    // Only accept messages from the chatbot iframe's origin
    if (event.origin !== chatbotOrigin) return;

    if (event.data?.type === "toggle-fullscreen") {
      if (event.data.isFullscreen) {
        document.body.classList.add("chatbot-fullscreen");
      } else {
        document.body.classList.remove("chatbot-fullscreen");
      }
    }

    if (event.data?.type === "close-chatbot") {
      document.body.classList.remove("show-chatbot");
      document.body.classList.remove("chatbot-fullscreen");
    }
  });

  document.head.insertAdjacentHTML("beforeend", googleIconsHTML);
}

// Auto-initialize when DOM is ready (for browser usage)
if (typeof document !== "undefined" && document.addEventListener) {
  document.addEventListener("DOMContentLoaded", initChatbot);
}
