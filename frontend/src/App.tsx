import { useEffect } from "react";
import { Routes, Route } from "react-router-dom";
import AlertProvider from "./components/ui/AlertProvider";
import WelcomeModal from "./components/ui/WelcomeModal";
import AppLayout from "./components/layout/AppLayout";
import Workbench from "./pages/Workbench";
import BatchWorkshop from "./pages/BatchWorkshop";
import History from "./pages/History";
import Settings from "./pages/Settings";
import About from "./pages/About";
import Logs from "./pages/Logs";
import SocialPublish from "./pages/SocialPublish";
import LLMRouter from "./pages/llm-router";
import EditingWorkbench from "./pages/EditingWorkbench";
import Collaboration from "./pages/Collaboration";
import Community from "./pages/Community";
import Guide from "./pages/Guide";
import { VoiceForgeAssets, VoiceForgeHome, VoiceForgeSettings, VoiceForgeVoices, VoiceForgeWorkspace } from "./pages/VoiceForge";
import { VoiceForgeLayout } from "./components/voiceforge/VoiceForgeLayout";
import { SceneDesignPlaceholder, VideoDubPlaceholder } from "./components/voiceforge/VoiceForgePlaceholders";
import { ensureControlSession } from "./api/controlPlane";
import { useControlStore } from "./stores/controlStore";
import { useSubscriptionStore } from "./stores/subscriptionStore";

function applyUISettings() {
  try {
    const theme = JSON.parse(localStorage.getItem("vl_theme") || '"system"');
    const root = document.documentElement;
    root.classList.remove("light", "dark");
    if (theme === "system") {
      root.classList.add(window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    } else {
      root.classList.add(theme);
    }

    const fontScale = JSON.parse(localStorage.getItem("vl_font_scale") || '"medium"');
    const sizes: Record<string, string> = { small: "14px", medium: "15px", large: "16px", xlarge: "18px" };
    if (sizes[fontScale]) document.documentElement.style.fontSize = sizes[fontScale];

    const fontFamily = JSON.parse(localStorage.getItem("vl_font_family") || '"plus-jakarta"');
    // Map old keys to new values for backward compatibility
    const familyMap: Record<string, string> = {
      default: '"Plus Jakarta Sans", system-ui, sans-serif',
      serif: '"Noto Serif", Georgia, serif',
      mono: '"JetBrains Mono", "Fira Code", monospace',
      "plus-jakarta": '"Plus Jakarta Sans", system-ui, sans-serif',
      inter: '"Inter", system-ui, sans-serif',
      "noto-sans": '"Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif',
      roboto: '"Roboto", system-ui, sans-serif',
      "source-han-sans": '"Source Han Sans SC", "Noto Sans SC", sans-serif',
      "noto-serif": '"Noto Serif", Georgia, serif',
      playfair: '"Playfair Display", Georgia, serif',
      merriweather: '"Merriweather", Georgia, serif',
      "jetbrains-mono": '"JetBrains Mono", "Fira Code", monospace',
      "fira-code": '"Fira Code", "Cascadia Code", monospace',
      system: "ui-sans-serif, system-ui, sans-serif",
    };
    if (familyMap[fontFamily]) document.body.style.fontFamily = familyMap[fontFamily];

    const mesh = JSON.parse(localStorage.getItem("vl_mesh_gradient") ?? "true");
    document.querySelector(".gradient-mesh")?.classList.toggle("no-mesh", !mesh);

    const reduceMotion = JSON.parse(localStorage.getItem("vl_reduce_motion") || "false");
    if (reduceMotion) document.documentElement.style.setProperty("--animation-duration", "0s");

    const navIcons = JSON.parse(localStorage.getItem("vl_nav_icons") ?? "true");
    document.body.classList.toggle("nav-icons-hidden", !navIcons);
  } catch {}
}

export default function App() {
  useEffect(() => {
    applyUISettings();
    // 启动期确保控制面会话：环回自动登录，未初始化则自动 bootstrap 默认管理员
    ensureControlSession()
      .then((user) => {
        if (user) useControlStore.getState().setUser(user);
      })
      .catch(() => undefined);
    // 启动时若存在“记住密码/自动登录”，用本地记忆的凭据向前端发起登录，
    // 真正写入后端 token；否则兜底向后端刷新一次权益状态。
    const sub = useSubscriptionStore.getState();
    sub.tryAutoLogin().catch(() => undefined).finally(() => {
      if (!useSubscriptionStore.getState().status?.is_logged_in) {
        sub.fetchStatus().catch(() => undefined);
      }
    });
  }, []);

  return (
    <AlertProvider>
      <WelcomeModal />
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Workbench />} />
          <Route path="/batch" element={<BatchWorkshop />} />
          <Route path="/history" element={<History />} />
          <Route path="/social" element={<SocialPublish />} />
          <Route path="/editing" element={<EditingWorkbench />} />
          <Route path="/voiceforge" element={<VoiceForgeLayout />}>
            <Route index element={<VoiceForgeHome />} />
            <Route path="projects/:projectId" element={<VoiceForgeWorkspace />} />
            <Route path="voices" element={<VoiceForgeVoices />} />
            <Route path="assets" element={<VoiceForgeAssets />} />
            <Route path="settings" element={<VoiceForgeSettings />} />
            <Route path="video-dub" element={<VideoDubPlaceholder />} />
            <Route path="scene-design" element={<SceneDesignPlaceholder />} />
          </Route>
          <Route path="/settings" element={<Settings />} />
          <Route path="/llm-router" element={<LLMRouter />} />
          <Route path="/collaboration" element={<Collaboration />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="/about" element={<About />} />
          <Route path="/community" element={<Community />} />
          <Route path="/guide" element={<Guide />} />
        </Route>
      </Routes>
    </AlertProvider>
  );
}
