import React, { createContext, useContext, useState, useEffect, ReactNode } from "react";
import zhCN from "./zh-CN.json";
import enUS from "./en-US.json";

export type Locale = "zh-CN" | "en-US";

const locales: Record<Locale, typeof zhCN> = {
  "zh-CN": zhCN,
  "en-US": enUS,
};

interface I18nContextType {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string) => string;
}

const I18nContext = createContext<I18nContextType>({
  locale: "zh-CN",
  setLocale: () => {},
  t: (key) => key,
});

function getNestedValue(obj: any, path: string): string {
  return path.split(".").reduce((acc, part) => acc?.[part], obj) ?? path;
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => {
    try {
      const saved = localStorage.getItem("app-locale");
      if (saved === "zh-CN" || saved === "en-US") return saved;
    } catch {}
    return "zh-CN";
  });

  const setLocale = (newLocale: Locale) => {
    setLocaleState(newLocale);
    try {
      localStorage.setItem("app-locale", newLocale);
    } catch {}
  };

  const t = (key: string): string => {
    return getNestedValue(locales[locale], key);
  };

  return (
    <I18nContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}

export const LOCALES: { value: Locale; label: string }[] = [
  { value: "zh-CN", label: "中文 (简体)" },
  { value: "en-US", label: "English" },
];
