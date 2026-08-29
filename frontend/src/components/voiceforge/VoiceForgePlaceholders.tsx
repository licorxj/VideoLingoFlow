import { Construction, Sparkles, Video } from "lucide-react";
import { PageBackground } from "@/components/shared/PageBackground";
import { PageHeader } from "@/components/shared/PageHeader";

function PlaceholderBody({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border/60 bg-card/40 p-16 text-muted-foreground">
      <Construction className="h-10 w-10 opacity-60" />
      <div className="text-sm">{message}</div>
    </div>
  );
}

export function VideoDubPlaceholder() {
  return (
    <PageBackground tone="voiceforge" className="mx-auto max-w-7xl space-y-5 p-1">
      <PageHeader
        icon={Video}
        title="视频配音"
        detail="为视频片段绑定配音轨道"
      />
      <PlaceholderBody message="功能建设中，敬请期待" />
    </PageBackground>
  );
}

export function SceneDesignPlaceholder() {
  return (
    <PageBackground tone="voiceforge" className="mx-auto max-w-7xl space-y-5 p-1">
      <PageHeader
        icon={Sparkles}
        title="场景设计"
        detail="编排配音场景与情绪"
      />
      <PlaceholderBody message="功能建设中，敬请期待" />
    </PageBackground>
  );
}
