import { Dialog, DialogContent } from "@/components/ui/dialog";
import { AssetLibrary } from "./AssetLibrary";

export function LocalAssetsModal({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] w-[95vw] max-w-[1200px] flex-col gap-0 overflow-hidden p-0">
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <AssetLibrary embedded />
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default LocalAssetsModal;
