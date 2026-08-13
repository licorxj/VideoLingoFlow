import { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { UserRound, KeyRound, Loader2, ShieldCheck, LogOut, CheckCircle2, AtSign } from "lucide-react";
import { registerUser, adminLogin, type CommunityUser } from "@/api/community";
import { useAlert } from "@/components/ui/AlertProvider";

/**
 * 身份设置弹窗：
 *  - 身份区：设置名称 + 邮箱并注册（云端仅做名称重复验证）
 *  - 管理员区：输入管理密钥登录（供管理员本人删除资源）
 */
export default function IdentityDialog(props: {
  open: boolean;
  baseUrl: string;
  user: CommunityUser | null;
  adminToken: string;
  onClose: () => void;
  onRegistered: (u: CommunityUser) => void;
  onAdminChange: (token: string) => void;
}) {
  const { alert } = useAlert();
  const [name, setName] = useState(props.user?.name || "");
  const [email, setEmail] = useState(props.user?.email || "");
  const [adminKey, setAdminKey] = useState("");
  const [regLoading, setRegLoading] = useState(false);
  const [loginLoading, setLoginLoading] = useState(false);

  const handleRegister = async () => {
    const n = name.trim();
    if (!n) {
      alert("请输入名称", "error");
      return;
    }
    setRegLoading(true);
    try {
      const u = await registerUser(props.baseUrl, n, email.trim());
      props.onRegistered(u);
      alert("身份注册成功（名称唯一验证通过）", "success");
    } catch (e: any) {
      alert(e?.message || "注册失败", "error");
    } finally {
      setRegLoading(false);
    }
  };

  const handleAdminLogin = async () => {
    const k = adminKey.trim();
    if (!k) {
      alert("请输入管理密钥", "error");
      return;
    }
    setLoginLoading(true);
    try {
      await adminLogin(props.baseUrl, k);
      props.onAdminChange(k);
      setAdminKey("");
      alert("管理员登录成功，可对资源执行删除操作", "success");
    } catch (e: any) {
      alert(e?.message || "管理员登录失败", "error");
    } finally {
      setLoginLoading(false);
    }
  };

  return (
    <Dialog open={props.open} onOpenChange={(o) => { if (!o) props.onClose(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserRound className="w-4 h-4 text-primary" /> 账号与身份
          </DialogTitle>
          <DialogDescription>设置你的社区身份，或登录管理员权限进行资源治理。</DialogDescription>
        </DialogHeader>

        {/* 身份注册 */}
        <div className="rounded-xl border border-border/60 bg-card/50 p-3.5 space-y-2.5">
          <div className="flex items-center gap-1.5 text-xs font-bold text-muted-foreground">
            <UserRound className="w-3.5 h-3.5" /> 设置身份（注册）
          </div>
          {props.user ? (
            <div className="flex items-center gap-2 text-sm bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
              <div className="min-w-0">
                <div className="font-semibold truncate">{props.user.name}</div>
                {props.user.email && <div className="text-[11px] text-muted-foreground truncate">{props.user.email}</div>}
              </div>
            </div>
          ) : null}
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="名称（唯一，最长 32 字符）"
            className="h-9 text-sm"
            maxLength={32}
          />
          <div className="relative">
            <AtSign className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/50" />
            <Input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="邮箱（可选）"
              className="h-9 text-sm pl-8"
              maxLength={64}
            />
          </div>
          <Button size="sm" className="w-full" onClick={handleRegister} disabled={regLoading || !name.trim()}>
            {regLoading && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}
            {props.user ? "更换身份并注册" : "注册"}
          </Button>
          <p className="text-[11px] text-muted-foreground/70">云端仅做名称重复验证，无重复即注册通过。</p>
        </div>

        {/* 管理员登录 */}
        <div className="rounded-xl border border-border/60 bg-card/50 p-3.5 space-y-2.5">
          <div className="flex items-center gap-1.5 text-xs font-bold text-muted-foreground">
            <KeyRound className="w-3.5 h-3.5" /> 管理员登录
          </div>
          {props.adminToken ? (
            <div className="flex items-center gap-2 text-sm bg-indigo-500/10 border border-indigo-500/25 rounded-lg px-3 py-2">
              <ShieldCheck className="w-4 h-4 text-indigo-500 flex-shrink-0" />
              <div className="flex-1 font-semibold">管理员已登录</div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => { props.onAdminChange(""); alert("已退出管理员登录", "success"); }}
              >
                <LogOut className="w-3 h-3 mr-1" /> 退出
              </Button>
            </div>
          ) : (
            <>
              <Input
                value={adminKey}
                onChange={(e) => setAdminKey(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleAdminLogin(); }}
                placeholder="管理密钥（仅管理员本人使用）"
                type="password"
                className="h-9 text-sm font-mono"
              />
              <Button size="sm" variant="outline" className="w-full" onClick={handleAdminLogin} disabled={loginLoading || !adminKey.trim()}>
                {loginLoading && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}
                登录管理员
              </Button>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
