import { useEffect, useMemo, useState } from "react";
import { BadgeCheck, Clock3, ExternalLink, KeyRound, Loader2, LogIn, LogOut, Mail, RefreshCw, ShieldCheck, Sparkles, Unplug, UserPlus, UsersRound } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useAlert } from "@/components/ui/AlertProvider";
import { getSubscriptionError, type Entitlement, type UserInfo } from "@/api/subscription";
import { useSubscriptionStore } from "@/stores/subscriptionStore";
import { cn } from "@/lib/utils";

const TYPE_LABEL = {
  guest: "游客",
  registered: "已注册用户",
  subscribed: "已订阅用户",
};

const TYPE_BADGE = {
  guest: "outline",
  registered: "warning",
  subscribed: "success",
} as const;

const REMEMBER_USERNAME_KEY = "vl_subscription_remember_username";
const REMEMBER_PASSWORD_KEY = "vl_subscription_remember_password";
const REMEMBER_ENABLED_KEY = "vl_subscription_remember_enabled";
const REMEMBER_PASSWORD_ENABLED_KEY = "vl_subscription_remember_password_enabled";
const AUTO_LOGIN_ENABLED_KEY = "vl_subscription_auto_login_enabled";

function hasLetterAndNumber(value: string) {
  return /[A-Za-z]/.test(value) && /\d/.test(value);
}

function getUsernameValidation(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return { valid: false, touched: false, message: "用户名需包含字母和数字，长度不少于 6 个字符" };
  }
  if (trimmed.length < 6) {
    return { valid: false, touched: true, message: "用户名长度不能少于 6 个字符" };
  }
  if (!hasLetterAndNumber(trimmed)) {
    return { valid: false, touched: true, message: "用户名需同时包含字母和数字" };
  }
  return { valid: true, touched: true, message: "用户名格式符合要求" };
}

function getPasswordValidation(value: string) {
  if (!value) {
    return { valid: false, touched: false, message: "密码需包含字母和数字，长度不少于 8 个字符" };
  }
  if (value.length < 8) {
    return { valid: false, touched: true, message: "密码长度不能少于 8 个字符" };
  }
  if (!hasLetterAndNumber(value)) {
    return { valid: false, touched: true, message: "密码需同时包含字母和数字" };
  }
  return { valid: true, touched: true, message: "密码格式符合要求" };
}

function getEntitlementProjectCode(item: Entitlement) {
  return String(item.software_code || item.softwareCode || item.software_id || item.softwareId || item.id || "");
}

function getEntitlementPoints(item: Entitlement | null | undefined) {
  if (!item) return "--";
  const value = item.remaining_points ?? item.points ?? item.total_points ?? item.quota_remaining ?? item.balance;
  return value === undefined || value === null ? "--" : String(value);
}

function getEntitlementDeviceLimit(item: Entitlement | null | undefined) {
  const value = item?.device_limit;
  return value === undefined || value === null ? "--" : String(value);
}

function getEntitlementBoundDeviceCount(item: Entitlement | null | undefined) {
  const value = item?.bound_device_count ?? item?.boundDeviceCount;
  return value === undefined || value === null ? "--" : String(value);
}

function getEntitlementTime(item: Entitlement | null | undefined) {
  return item?.valid_until || item?.validUntil || item?.expire_at || item?.expires_at || "";
}

function formatDateTime(value: string | undefined | null) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatRemainingTime(value: string | undefined | null) {
  if (!value) return "--";
  const target = new Date(value).getTime();
  if (Number.isNaN(target)) return String(value);
  const diff = target - Date.now();
  if (diff <= 0) return "已过期";
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));
  const hours = Math.floor((diff / (1000 * 60 * 60)) % 24);
  return days > 0 ? `${days} 天 ${hours} 小时` : `${hours} 小时`;
}

function SummaryField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-border/50 bg-background/60 px-4 py-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-sm font-semibold break-all">{value || "--"}</div>
    </div>
  );
}

function PreferenceToggle({
  checked,
  title,
  onChange,
}: {
  checked: boolean;
  title: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-all duration-200",
        checked
          ? "border-primary/40 bg-primary/10 shadow-sm shadow-primary/10"
          : "border-border/50 bg-background/50 hover:border-primary/25 hover:bg-primary/5"
      )}
    >
      <span
        className={cn(
          "flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-all",
          checked
            ? "border-primary bg-primary text-primary-foreground"
            : "border-border/70 bg-background"
        )}
      >
        <span
          className={cn(
            "h-2 w-2 rounded-full transition-all",
            checked ? "bg-current" : "bg-transparent"
          )}
        />
      </span>
      <span className="font-medium text-foreground">{title}</span>
    </button>
  );
}

export default function UserSubscription({ embedded = false }: { embedded?: boolean }) {
  const { alert: showAlert } = useAlert();
  const { status, loading, error, fetchStatus, refresh, login, logout, unbindDevice, register, sendCode, sendResetCode, resetPassword, verifyCard } = useSubscriptionStore();
  const [loginForm, setLoginForm] = useState({ username: "", password: "" });
  const [rememberUsername, setRememberUsername] = useState(false);
  const [rememberPassword, setRememberPassword] = useState(false);
  const [autoLogin, setAutoLogin] = useState(false);
  const [registerForm, setRegisterForm] = useState({ username: "", password: "", email: "", phone: "", verification_code: "" });
  const [cardCode, setCardCode] = useState("");
  const [registerOpen, setRegisterOpen] = useState(false);
  const [resetPasswordOpen, setResetPasswordOpen] = useState(false);
  const [resetPasswordForm, setResetPasswordForm] = useState({ email: "", code: "", new_password: "" });

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    try {
      const enabled = localStorage.getItem(REMEMBER_ENABLED_KEY) === "true";
      const passwordEnabled = localStorage.getItem(REMEMBER_PASSWORD_ENABLED_KEY) === "true";
      const autoLoginEnabled = localStorage.getItem(AUTO_LOGIN_ENABLED_KEY) === "true";
      const username = localStorage.getItem(REMEMBER_USERNAME_KEY) || "";
      const password = localStorage.getItem(REMEMBER_PASSWORD_KEY) || "";
      setRememberUsername(enabled || passwordEnabled || autoLoginEnabled);
      setRememberPassword(passwordEnabled || autoLoginEnabled);
      setAutoLogin(autoLoginEnabled);
      setLoginForm({
        username: enabled || passwordEnabled || autoLoginEnabled ? username : "",
        password: passwordEnabled || autoLoginEnabled ? password : "",
      });
    } catch {
      setRememberUsername(false);
      setRememberPassword(false);
      setAutoLogin(false);
    }
  }, []);

  useEffect(() => {
    if (!autoLogin || loading || status?.is_logged_in) return;
    if (!loginForm.username.trim() || !loginForm.password.trim()) return;
    let cancelled = false;

    const runAutoLogin = async () => {
      try {
        await login({
          username: loginForm.username.trim(),
          password: loginForm.password,
        });
        if (!cancelled) showAlert("已自动登录", "success");
      } catch (e) {
        if (!cancelled) showAlert(getSubscriptionError(e), "error");
      }
    };

    runAutoLogin();
    return () => {
      cancelled = true;
    };
  }, [autoLogin, loading, status?.is_logged_in]);

  const userType = status?.user_type || "guest";
  const links = {
    ...status?.links,
    products: "https://68n.cn/PUweA",
    home: "https://www.licorxj.online/home",
    versions: "https://www.licorxj.online/versions",
  };
  const activeEntitlement = status?.active_entitlement || null;
  const projectEntitlements = useMemo(() => (status?.entitlements || []).filter((item) => getEntitlementProjectCode(item) === "vlf3387"), [status?.entitlements]);
  const usernameValidation = getUsernameValidation(registerForm.username);
  const passwordValidation = getPasswordValidation(registerForm.password);

  const dailyUsage = status?.daily_node_usage ?? status?.daily_usage ?? 0;
  const dailyLimit = status?.daily_node_limit ?? status?.daily_limit;
  const remainingToday = status?.remaining_nodes_today ?? status?.remaining_today ?? 0;
  const canExecuteNode = status?.can_execute_node ?? status?.can_create_task;
  const usageText = dailyLimit == null
    ? "无限畅饮"
    : `${dailyUsage}/${dailyLimit}，今日剩余 ${remainingToday}`;

  const summaryEntitlement = activeEntitlement || projectEntitlements[0] || null;

  const handleLogin = async () => {
    if (!loginForm.username.trim() || !loginForm.password.trim()) return showAlert("请输入用户名和密码", "warning");
    try {
      await login(loginForm);
      try {
        if (rememberUsername || rememberPassword || autoLogin) {
          localStorage.setItem(REMEMBER_ENABLED_KEY, "true");
          localStorage.setItem(REMEMBER_USERNAME_KEY, loginForm.username.trim());
        } else {
          localStorage.removeItem(REMEMBER_ENABLED_KEY);
          localStorage.removeItem(REMEMBER_USERNAME_KEY);
        }
        if (rememberPassword || autoLogin) {
          localStorage.setItem(REMEMBER_PASSWORD_ENABLED_KEY, "true");
          localStorage.setItem(REMEMBER_PASSWORD_KEY, loginForm.password);
        } else {
          localStorage.removeItem(REMEMBER_PASSWORD_ENABLED_KEY);
          localStorage.removeItem(REMEMBER_PASSWORD_KEY);
        }
        if (autoLogin) localStorage.setItem(AUTO_LOGIN_ENABLED_KEY, "true");
        else localStorage.removeItem(AUTO_LOGIN_ENABLED_KEY);
      } catch {}
      showAlert("登录成功", "success");
    } catch (e) {
      showAlert(getSubscriptionError(e), "error");
    }
  };

  const handleLogout = async () => {
    try {
      await logout();
      showAlert("已退出登录", "success");
    } catch (e) {
      showAlert(getSubscriptionError(e), "error");
    }
  };

  const handleUnbindDevice = async () => {
    try {
      await unbindDevice();
      setAutoLogin(false);
      try {
        localStorage.removeItem(AUTO_LOGIN_ENABLED_KEY);
      } catch {}
      showAlert("当前设备已解绑，并已安全退出登录", "success");
    } catch (e) {
      showAlert(getSubscriptionError(e), "error");
    }
  };

  const handleSendCode = async () => {
    if (!registerForm.email.trim()) return showAlert("请输入邮箱", "warning");
    try {
      await sendCode(registerForm.email.trim());
      showAlert("验证码已发送，请查收邮箱", "success");
    } catch (e) {
      showAlert(getSubscriptionError(e), "error");
    }
  };

  const handleRegister = async () => {
    if (!registerForm.username.trim() || !registerForm.password.trim() || !registerForm.email.trim()) return showAlert("请填写用户名、密码和邮箱", "warning");
    if (!usernameValidation.valid) return showAlert(usernameValidation.message, "warning");
    if (!passwordValidation.valid) return showAlert(passwordValidation.message, "warning");
    try {
      await register({ ...registerForm, phone: registerForm.phone || undefined, verification_code: registerForm.verification_code || undefined });
      setRegisterOpen(false);
      showAlert("注册成功，请使用新账号登录", "success");
    } catch (e) {
      showAlert(getSubscriptionError(e), "error");
    }
  };

  const handleSendResetCode = async () => {
    if (!resetPasswordForm.email.trim()) return showAlert("请输入邮箱", "warning");
    try {
      await sendResetCode(resetPasswordForm.email.trim());
      showAlert("重置验证码已发送，请查收邮箱", "success");
    } catch (e) {
      showAlert(getSubscriptionError(e), "error");
    }
  };

  const handleResetPassword = async () => {
    if (!resetPasswordForm.email.trim() || !resetPasswordForm.code.trim() || !resetPasswordForm.new_password) {
      return showAlert("请填写邮箱、验证码和新密码", "warning");
    }
    const validation = getPasswordValidation(resetPasswordForm.new_password);
    if (!validation.valid) return showAlert(validation.message, "warning");
    try {
      await resetPassword({
        email: resetPasswordForm.email.trim(),
        code: resetPasswordForm.code.trim(),
        new_password: resetPasswordForm.new_password,
      });
      setResetPasswordOpen(false);
      setResetPasswordForm({ email: "", code: "", new_password: "" });
      showAlert("密码已重置，请使用新密码登录", "success");
    } catch (e) {
      showAlert(getSubscriptionError(e), "error");
    }
  };

  const handleVerifyCard = async () => {
    if (!cardCode.trim()) return showAlert("请输入卡密", "warning");
    try {
      await verifyCard(cardCode.trim());
      setCardCode("");
      showAlert("验码成功，权益已刷新", "success");
    } catch (e) {
      showAlert(getSubscriptionError(e), "error");
    }
  };

  const handleRefresh = async () => {
    const latest = await refresh();
    showAlert(latest ? "订阅数据已刷新" : "刷新失败，请稍后重试", latest ? "success" : "error");
  };

  const handleRememberUsernameChange = (checked: boolean) => {
    setRememberUsername(checked);
    if (!checked) {
      setRememberPassword(false);
      setAutoLogin(false);
    }
  };

  const handleRememberPasswordChange = (checked: boolean) => {
    setRememberPassword(checked);
    if (checked) {
      setRememberUsername(true);
      return;
    }
    setAutoLogin(false);
  };

  const handleAutoLoginChange = (checked: boolean) => {
    setAutoLogin(checked);
    if (checked) {
      setRememberUsername(true);
      setRememberPassword(true);
    }
  };

  const openLink = (url: string) => window.open(url, "_blank", "noopener,noreferrer");

  return (
    <div className={cn("space-y-5", !embedded && "max-w-7xl mx-auto")}>
      {!embedded && (
        <div className="relative overflow-hidden rounded-3xl border border-border/60 bg-card shadow-sm">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(59,130,246,0.16),transparent_34%),radial-gradient(circle_at_bottom_right,rgba(16,185,129,0.14),transparent_30%)]" />
          <div className="relative p-6 md:p-8 flex flex-col lg:flex-row gap-6 lg:items-end lg:justify-between">
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <div className="w-11 h-11 rounded-2xl bg-primary/10 text-primary flex items-center justify-center">
                  <ShieldCheck className="w-6 h-6" />
                </div>
                <div>
                  <h2 className="text-2xl font-extrabold tracking-tight">用户和订阅</h2>
                  <p className="text-sm text-muted-foreground">连接晴沐智坊云端会员系统，管理登录、权益和本地使用额度</p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={TYPE_BADGE[userType]} className="px-3 py-1">{TYPE_LABEL[userType]}</Badge>
                <Badge variant="outline" className="px-3 py-1">软件 ID：{status?.software_id || "vlf3387"}</Badge>
                <Badge variant={canExecuteNode ? "success" : "destructive"} className="px-3 py-1">{canExecuteNode ? "可执行节点" : "额度不足"}</Badge>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 min-w-[300px]">
              <div className="rounded-2xl bg-background/70 border border-border/50 p-4">
                <div className="text-xs text-muted-foreground">每日节点额度</div>
                <div className="text-lg font-bold mt-1">{usageText}</div>
              </div>
              <div className="rounded-2xl bg-background/70 border border-border/50 p-4">
                <div className="text-xs text-muted-foreground">订阅权益</div>
                <div className="text-lg font-bold mt-1">{projectEntitlements.length || 0} 条</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {error && <div className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-500">{error}</div>}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><LogIn className="w-5 h-5 text-primary" />登录</CardTitle>
            <CardDescription>登录后可查看权益并解锁订阅能力</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input value={loginForm.username} onChange={(e) => setLoginForm((v) => ({ ...v, username: e.target.value }))} placeholder="用户名" />
            <Input type="password" value={loginForm.password} onChange={(e) => setLoginForm((v) => ({ ...v, password: e.target.value }))} placeholder="密码" />
            <div className="flex flex-wrap gap-2">
              <PreferenceToggle
                checked={rememberUsername}
                title="记住账号"
                onChange={handleRememberUsernameChange}
              />
              <PreferenceToggle
                checked={rememberPassword}
                title="记住密码"
                onChange={handleRememberPasswordChange}
              />
              <PreferenceToggle
                checked={autoLogin}
                title="自动登录"
                onChange={handleAutoLoginChange}
              />
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              <Button onClick={handleLogin} disabled={loading} className="sm:flex-1">
                {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <LogIn className="w-4 h-4 mr-2" />}
                登录
              </Button>
              <Button onClick={() => setRegisterOpen(true)} variant="outline" className="sm:flex-1">
                <UserPlus className="w-4 h-4 mr-2" />
                注册
              </Button>
            </div>
            <Button onClick={() => setResetPasswordOpen(true)} disabled={loading} variant="ghost" className="w-full">
              <KeyRound className="w-4 h-4 mr-2" />
              找回密码
            </Button>
            <Button onClick={handleLogout} disabled={loading || !status?.is_logged_in} variant="outline" className="w-full">
              <LogOut className="w-4 h-4 mr-2" />
              退出当前账号
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Clock3 className="w-5 h-5 text-primary" />当前状态</CardTitle>
            <CardDescription>账号状态与额度概览</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className={cn("rounded-2xl border p-4", userType === "subscribed" ? "border-emerald-500/40 bg-emerald-500/5" : "border-border/50 bg-background/60")}>
              <div className="text-xs text-muted-foreground">当前用户类型</div>
              <div className="mt-1 flex items-center gap-2">
                <div className="text-lg font-bold">{TYPE_LABEL[userType]}</div>
                <Badge variant={TYPE_BADGE[userType]}>{TYPE_LABEL[userType]}</Badge>
              </div>
            </div>
            <div className="rounded-2xl border border-border/50 bg-background/60 p-4">
              <div className="text-xs text-muted-foreground">节点额度信息</div>
              <div className="mt-1 text-base font-semibold">{usageText}</div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-4">
              <div>
                <CardTitle className="flex items-center gap-2"><UsersRound className="w-5 h-5 text-primary" />账号与订阅</CardTitle>
                <CardDescription className="mt-1.5">将用户信息和本项目订阅状态集中展示</CardDescription>
              </div>
              <Button onClick={handleRefresh} disabled={loading} variant="outline" size="sm" title="刷新账号和订阅权益">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                <span className="ml-2">刷新数据</span>
              </Button>
            </div>
          </CardHeader>
          <CardContent className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="space-y-3">
              <div className="text-sm font-semibold">用户信息</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <SummaryField label="用户名" value={status?.user_info?.username || "--"} />
                <SummaryField label="邮箱号" value={status?.user_info?.email || "--"} />
                <SummaryField label="是否激活" value={status?.user_info?.is_active ? "已激活" : "未激活"} />
                <SummaryField label="注册时间" value={formatDateTime(status?.user_info?.created_at)} />
                <div className="md:col-span-2">
                  <SummaryField label="上次登录时间" value={formatDateTime(status?.user_info?.last_login)} />
                </div>
              </div>
            </div>
            <div className="space-y-3">
              <div className="text-sm font-semibold">订阅权益</div>
              <div className="grid grid-cols-1 gap-3">
                <SummaryField label="剩余时间" value={formatRemainingTime(getEntitlementTime(summaryEntitlement))} />
                <SummaryField label="剩余积分点" value={getEntitlementPoints(summaryEntitlement)} />
                <SummaryField label="上次验证时间点" value={formatDateTime(summaryEntitlement?.last_granted_at)} />
              </div>
              <div className="flex flex-col gap-3 rounded-2xl border border-primary/15 bg-primary/5 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-sm font-medium text-foreground">
                  当前已绑定 {getEntitlementBoundDeviceCount(summaryEntitlement)}/{getEntitlementDeviceLimit(summaryEntitlement)} 台设备
                </div>
                <Button
                  onClick={handleUnbindDevice}
                  disabled={loading || !status?.is_logged_in}
                  variant="outline"
                  size="sm"
                  className="sm:min-w-[132px]"
                >
                  {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Unplug className="mr-2 h-4 w-4" />}
                  解绑当前设备
                </Button>
              </div>
            </div>
          </CardContent>
      </Card>

      <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><KeyRound className="w-5 h-5 text-primary" />快捷验码</CardTitle>
            <CardDescription>登录后输入卡密，快速刷新本项目订阅权益</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col md:flex-row gap-3">
            <Input value={cardCode} onChange={(e) => setCardCode(e.target.value)} placeholder="请输入卡密" className="md:flex-1" />
            <Button onClick={handleVerifyCard} disabled={loading} className="md:min-w-[200px]">
              {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <BadgeCheck className="w-4 h-4 mr-2" />}
              验证并刷新权益
            </Button>
          </CardContent>
      </Card>

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Sparkles className="w-5 h-5 text-primary" />快捷入口</CardTitle>
          <CardDescription>将常用入口收纳到页面底部，减少主视区干扰</CardDescription>
        </CardHeader>
        <CardContent className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          {[
            ["购买订阅", "开通或续费当前软件权益", links.products],
            ["晴沐智坊主页", "访问账号与产品主页", links.home],
            ["软件中心", "查看版本与更新信息", links.versions],
          ].map(([title, desc, url]) => (
            <button key={url} onClick={() => openLink(url)} className="w-full text-left rounded-2xl border border-border/60 bg-background/60 px-4 py-4 hover:border-primary/40 hover:bg-primary/5 transition-all active:scale-[0.99]">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="font-bold">{title}</div>
                  <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{desc}</p>
                </div>
                <ExternalLink className="w-4 h-4 shrink-0 text-muted-foreground" />
              </div>
            </button>
          ))}
        </CardContent>
      </Card>

      <Dialog open={registerOpen} onOpenChange={setRegisterOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><UserPlus className="w-5 h-5 text-primary" />注册账号</DialogTitle>
            <DialogDescription>通过邮箱验证码创建新的晴沐智坊云端账号</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Input
                  value={registerForm.username}
                  onChange={(e) => setRegisterForm((v) => ({ ...v, username: e.target.value }))}
                  placeholder="用户名（需含字母和数字，至少 6 位）"
                  className={usernameValidation.touched && !usernameValidation.valid ? "border-red-500/60 focus-visible:ring-red-500/30" : ""}
                />
                <div className={cn("text-xs", usernameValidation.touched ? (usernameValidation.valid ? "text-emerald-600" : "text-red-500") : "text-muted-foreground")}>
                  {usernameValidation.message}
                </div>
              </div>
              <div className="space-y-1.5">
                <Input
                  type="password"
                  value={registerForm.password}
                  onChange={(e) => setRegisterForm((v) => ({ ...v, password: e.target.value }))}
                  placeholder="密码（需含字母和数字，至少 8 位）"
                  className={passwordValidation.touched && !passwordValidation.valid ? "border-red-500/60 focus-visible:ring-red-500/30" : ""}
                />
                <div className={cn("text-xs", passwordValidation.touched ? (passwordValidation.valid ? "text-emerald-600" : "text-red-500") : "text-muted-foreground")}>
                  {passwordValidation.message}
                </div>
              </div>
              <Input value={registerForm.email} onChange={(e) => setRegisterForm((v) => ({ ...v, email: e.target.value }))} placeholder="邮箱" />
              <Input value={registerForm.phone} onChange={(e) => setRegisterForm((v) => ({ ...v, phone: e.target.value }))} placeholder="手机号（可选）" />
            </div>
            <div className="flex flex-col md:flex-row gap-2">
              <Input value={registerForm.verification_code} onChange={(e) => setRegisterForm((v) => ({ ...v, verification_code: e.target.value }))} placeholder="邮箱验证码" className="md:flex-1" />
              <Button onClick={handleSendCode} disabled={loading} variant="outline" className="md:min-w-[160px]">
                <Mail className="w-4 h-4 mr-2" />
                发送验证码
              </Button>
            </div>
            <Button onClick={handleRegister} disabled={loading} className="w-full">
              <UserPlus className="w-4 h-4 mr-2" />
              注册账号
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={resetPasswordOpen} onOpenChange={setResetPasswordOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><KeyRound className="w-5 h-5 text-primary" />找回密码</DialogTitle>
            <DialogDescription>通过邮箱验证码设置新的登录密码</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input value={resetPasswordForm.email} onChange={(e) => setResetPasswordForm((v) => ({ ...v, email: e.target.value }))} placeholder="注册邮箱" />
            <div className="flex flex-col md:flex-row gap-2">
              <Input value={resetPasswordForm.code} onChange={(e) => setResetPasswordForm((v) => ({ ...v, code: e.target.value }))} placeholder="邮箱验证码" className="md:flex-1" />
              <Button onClick={handleSendResetCode} disabled={loading} variant="outline" className="md:min-w-[160px]"><Mail className="w-4 h-4 mr-2" />发送验证码</Button>
            </div>
            <Input type="password" value={resetPasswordForm.new_password} onChange={(e) => setResetPasswordForm((v) => ({ ...v, new_password: e.target.value }))} placeholder="新密码（需含字母和数字，至少 8 位）" />
            <Button onClick={handleResetPassword} disabled={loading} className="w-full"><KeyRound className="w-4 h-4 mr-2" />重置密码</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
