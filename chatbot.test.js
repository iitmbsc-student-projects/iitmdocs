import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { JSDOM } from "jsdom";
import { chatbotCSS, getChatbotHTML, addChatbotStyles, initChatbot } from "./static/chatbot.js";

describe("Chatbot Fullscreen Mode", () => {
  let dom;
  let document;
  let window;

  beforeEach(() => {
    dom = new JSDOM("<!DOCTYPE html><html><head></head><body></body></html>", {
      url: "http://localhost",
    });
    document = dom.window.document;
    window = dom.window;

    // Set up global document and window for the chatbot module
    global.document = document;
    global.window = window;
  });

  afterEach(() => {
    delete global.document;
    delete global.window;
  });

  describe("CSS Styles", () => {
    it("should include fullscreen state styles", () => {
      expect(chatbotCSS).toContain("body.chatbot-fullscreen .chatbot");
    });

    it("should define fullscreen dimensions with space for X button", () => {
      expect(chatbotCSS).toContain("width: 95vw");
      expect(chatbotCSS).toContain("height: calc(100vh - 100px)");
      expect(chatbotCSS).toContain("bottom: 90px");
    });

    it("should not hide chatbot-toggler in fullscreen mode", () => {
      // The X button (chatbot-toggler) should remain visible in fullscreen
      expect(chatbotCSS).not.toMatch(/body\.chatbot-fullscreen[^{]*\.chatbot-toggler[^{]*\{[^}]*display:\s*none/);
    });
  });

  describe("HTML Structure", () => {
    const testHTML = getChatbotHTML('', '');

    it("should include chatbot toggler button (X button)", () => {
      expect(testHTML).toContain('class="chatbot-toggler"');
    });

    it("should include close icon", () => {
      expect(testHTML).toContain(">close<");
    });

    it("should include chatbox with iframe", () => {
      expect(testHTML).toContain('class="chatbox"');
      expect(testHTML).toContain("<iframe");
      expect(testHTML).toContain('src="qa.html?program_id=ds"');
    });

    it("should include parentOrigin parameter when provided", () => {
      const htmlWithOrigin = getChatbotHTML('https://example.com/', 'https://parent.com');
      expect(htmlWithOrigin).toContain('src="https://example.com/qa.html?parentOrigin=https%3A%2F%2Fparent.com&program_id=ds"');
    });

    it("should include program_id parameter when provided", () => {
      const htmlWithProgram = getChatbotHTML('https://example.com/', 'https://parent.com', 'es');
      expect(htmlWithProgram).toContain('program_id=es');
    });
  });

  describe("Fullscreen Toggle via postMessage", () => {
    beforeEach(() => {
      initChatbot();
    });

    it("should add chatbot-fullscreen class when receiving fullscreen message", () => {
      expect(document.body.classList.contains("chatbot-fullscreen")).toBe(false);

      // Simulate postMessage from iframe with valid origin
      const event = new window.MessageEvent("message", {
        data: { type: "toggle-fullscreen", isFullscreen: true },
        origin: window.location.origin,
      });
      window.dispatchEvent(event);

      expect(document.body.classList.contains("chatbot-fullscreen")).toBe(true);
    });

    it("should remove chatbot-fullscreen class when receiving minimize message", () => {
      // First set fullscreen
      document.body.classList.add("chatbot-fullscreen");
      expect(document.body.classList.contains("chatbot-fullscreen")).toBe(true);

      // Simulate postMessage to minimize with valid origin
      const event = new window.MessageEvent("message", {
        data: { type: "toggle-fullscreen", isFullscreen: false },
        origin: window.location.origin,
      });
      window.dispatchEvent(event);

      expect(document.body.classList.contains("chatbot-fullscreen")).toBe(false);
    });

    it("should ignore messages with wrong type", () => {
      expect(document.body.classList.contains("chatbot-fullscreen")).toBe(false);

      const event = new window.MessageEvent("message", {
        data: { type: "other-message", isFullscreen: true },
        origin: window.location.origin,
      });
      window.dispatchEvent(event);

      expect(document.body.classList.contains("chatbot-fullscreen")).toBe(false);
    });

    it("should ignore messages from wrong origin", () => {
      expect(document.body.classList.contains("chatbot-fullscreen")).toBe(false);

      // Simulate postMessage from malicious origin
      const event = new window.MessageEvent("message", {
        data: { type: "toggle-fullscreen", isFullscreen: true },
        origin: "https://evil.com",
      });
      window.dispatchEvent(event);

      // Should NOT toggle fullscreen from untrusted origin
      expect(document.body.classList.contains("chatbot-fullscreen")).toBe(false);
    });

    it("should not affect show-chatbot class when toggling fullscreen", () => {
      const chatbotToggler = document.querySelector(".chatbot-toggler");

      // Open chatbot first
      chatbotToggler.click();
      expect(document.body.classList.contains("show-chatbot")).toBe(true);

      // Toggle fullscreen via message
      const fullscreenEvent = new window.MessageEvent("message", {
        data: { type: "toggle-fullscreen", isFullscreen: true },
        origin: window.location.origin,
      });
      window.dispatchEvent(fullscreenEvent);

      expect(document.body.classList.contains("chatbot-fullscreen")).toBe(true);
      expect(document.body.classList.contains("show-chatbot")).toBe(true);

      // Minimize via message
      const minimizeEvent = new window.MessageEvent("message", {
        data: { type: "toggle-fullscreen", isFullscreen: false },
        origin: window.location.origin,
      });
      window.dispatchEvent(minimizeEvent);

      expect(document.body.classList.contains("chatbot-fullscreen")).toBe(false);
      expect(document.body.classList.contains("show-chatbot")).toBe(true);
    });

    it("should keep chatbot-toggler (X button) clickable in fullscreen mode", () => {
      const chatbotToggler = document.querySelector(".chatbot-toggler");

      // Open chatbot and go fullscreen
      chatbotToggler.click();
      const fullscreenEvent = new window.MessageEvent("message", {
        data: { type: "toggle-fullscreen", isFullscreen: true },
        origin: window.location.origin,
      });
      window.dispatchEvent(fullscreenEvent);

      expect(document.body.classList.contains("show-chatbot")).toBe(true);
      expect(document.body.classList.contains("chatbot-fullscreen")).toBe(true);

      // Click X button to close - should still work
      chatbotToggler.click();
      expect(document.body.classList.contains("show-chatbot")).toBe(false);
    });
  });

  describe("addChatbotStyles()", () => {
    it("should add styles to document head", () => {
      addChatbotStyles();

      const styleElement = document.getElementById("chatbot-styles");
      expect(styleElement).not.toBeNull();
      expect(styleElement.tagName).toBe("STYLE");
    });

    it("should include fullscreen state styles in the style element", () => {
      addChatbotStyles();

      const styleElement = document.getElementById("chatbot-styles");
      expect(styleElement.innerHTML).toContain("body.chatbot-fullscreen");
    });

    it("should not add duplicate styles when called multiple times", () => {
      addChatbotStyles();
      addChatbotStyles();
      addChatbotStyles();

      const styleElements = document.querySelectorAll("#chatbot-styles");
      expect(styleElements.length).toBe(1);
    });
  });
});
