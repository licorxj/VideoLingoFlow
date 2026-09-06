import { Dialog, DialogContent } from "@/components/ui/dialog";
import { VoiceForgeAsset } from "@/api/voiceforge";
import { AssetLibrary } from "./AssetLibrary";

export function LocalAssetsModal({
  open,
  onOpenChange,
  onPick,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  /** 提供后进入选择模式:每个素材卡片带「选择」按钮,选中即回传素材记录 */
  onPick?: (asset: VoiceForgeAsset) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] w-[95vw] max-w-[1200px] flex-col gap-0 overflow-hidden p-0">
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <AssetLibrary embedded onPick={onPick} />
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default LocalAssetsModal;
