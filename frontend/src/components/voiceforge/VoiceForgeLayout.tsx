import { Outlet } from "react-router-dom";
import { VoiceForgeTopNav } from "./VoiceForgeTopNav";

export function VoiceForgeLayout() {
  return (
    <>
      <VoiceForgeTopNav />
      <Outlet />
    </>
  );
}
