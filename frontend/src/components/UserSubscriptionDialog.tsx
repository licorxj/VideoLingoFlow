import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { ShieldCheck } from "lucide-react";
import UserSubscription from "@/pages/UserSubscription";

interface UserSubscriptionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export default function UserSubscriptionDialog({ open, onOpenChange }: UserSubscriptionDialogProps) {
  const preventAlertOutsideInteraction = (event: { target: EventTarget | null; preventDefault: () => void }) => {
    if ((event.target as HTMLElement | null)?.closest("#avl-alert-overlay")) event.preventDefault();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-[95vw] max-h-[90vh] overflow-y-auto p-0 sm:max-w-4xl"
        onInteractOutside={preventAlertOutsideInteraction}
        onPointerDownOutside={preventAlertOutsideInteraction}
        onFocusOutside={preventAlertOutsideInteraction}
      >
        <DialogHeader className="px-6 pt-6 pb-2">
          <DialogTitle className="flex items-center gap-2 text-lg">
            <ShieldCheck className="w-5 h-5 text-primary" />
            用户和订阅
          </DialogTitle>
          <DialogDescription>
            连接晴沐智坊云端会员系统，管理登录、权益和本地使用额度
          </DialogDescription>
        </DialogHeader>
        <div className="px-6 pb-6">
          <UserSubscription embedded />
        </div>
      </DialogContent>
    </Dialog>
  );
}
