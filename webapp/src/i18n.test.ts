import { describe, expect, it } from "vitest";
import { DICT, dirOf, num, pickLang, translate } from "./i18n";

describe("i18n", () => {
  it("has the same keys in fa and en", () => {
    expect(Object.keys(DICT.en).sort()).toEqual(Object.keys(DICT.fa).sort());
  });
  it("has no empty strings", () => {
    for (const l of ["fa", "en"] as const) for (const [k, v] of Object.entries(DICT[l])) expect(v.trim(), `${l}.${k}`).not.toBe("");
  });
  it("interpolates variables", () => {
    expect(translate("en", "home.hello", { name: "Ali" })).toBe("Hi Ali");
    expect(translate("fa", "feature.stage", { n: "۲" })).toBe("مرحله ۲");
  });
  it("direction and digits", () => {
    expect(dirOf("fa")).toBe("rtl");
    expect(dirOf("en")).toBe("ltr");
    expect(num("fa", 2026)).toBe("۲۰۲۶");
    expect(num("en", 2026)).toBe("2026");
  });
  it("picks language from telegram code", () => {
    expect(pickLang("fa-IR")).toBe("fa");
    expect(pickLang("en")).toBe("en");
    expect(pickLang("de")).toBe("en");
    expect(pickLang(undefined)).toBe("fa");
  });
});
