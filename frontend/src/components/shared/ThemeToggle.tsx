import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Sun, Moon } from "lucide-react";

export default function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("theme");
    if (
      saved === "dark" ||
      (!saved && window.matchMedia("(prefers-color-scheme: dark)").matches)
    ) {
      setDark(true);
      document.documentElement.classList.add("dark");
    }
  }, []);

  const toggle = () => {
    const next = !dark;
    setDark(next);
    if (next) {
      document.documentElement.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("theme", "light");
    }
  };

  return (
    <button
      onClick={toggle}
      className={cn(
        "relative p-2 rounded-xl transition-all duration-300",
        "hover:bg-accent text-muted-foreground hover:text-foreground",
        "active:scale-90"
      )}
      title={dark ? "切换到亮色模式" : "切换到暗色模式"}
    >
      <div className="relative w-[18px] h-[18px]">
        <Sun
          className={cn(
            "absolute inset-0 w-[18px] h-[18px] transition-all duration-300",
            dark
              ? "rotate-90 scale-0 opacity-0"
              : "rotate-0 scale-100 opacity-100"
          )}
          strokeWidth={2}
        />
        <Moon
          className={cn(
            "absolute inset-0 w-[18px] h-[18px] transition-all duration-300",
            dark
              ? "rotate-0 scale-100 opacity-100"
              : "-rotate-90 scale-0 opacity-0"
          )}
          strokeWidth={2}
        />
      </div>
    </button>
  );
}
