import { readFileSync } from "fs";
import { describe, expect, it } from "vitest";
import { JSDOM } from "jsdom";

const faqAdminCss = readFileSync("static/faq-admin.css", "utf8");

describe("FAQ admin add-flow information button", () => {
  it("hides the question information button until the add flow starts", () => {
    const dom = new JSDOM(
      `<style>${faqAdminCss}</style><button class="question-lock-info" hidden>i</button>`,
    );

    const button = dom.window.document.querySelector(".question-lock-info");

    expect(dom.window.getComputedStyle(button).display).toBe("none");
  });

  it("keeps the visible information button level with the Question label", () => {
    const dom = new JSDOM(
      `<style>${faqAdminCss}</style><div class="question-label-row"><label>Question</label><button class="question-lock-info">i</button></div>`,
    );
    const button = dom.window.document.querySelector(".question-lock-info");
    const label = dom.window.document.querySelector(".question-label-row label");

    expect(dom.window.getComputedStyle(button).marginTop).toBe("0px");
    expect(dom.window.getComputedStyle(label).marginTop).toBe("0px");
  });
});
