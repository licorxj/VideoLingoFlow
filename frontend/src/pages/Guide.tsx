import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, FileText, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

// 文档按照使用顺序排列
const DOC_FILES = [
  { id: "quick-start", file: "快速开始.md", label: "快速开始" },
  { id: "architecture", file: "项目架构.md", label: "项目架构" },
  { id: "directory", file: "项目目录功能说明.md", label: "目录说明" },
  { id: "workflow", file: "工作流编排指南.md", label: "工作流编排" },
  { id: "node-guide", file: "节点新建规范指南.md", label: "节点规范" },
  { id: "interface-guide", file: "接口添加指南.md", label: "接口添加" },
  { id: "dependencies", file: "依赖清单.md", label: "依赖清单" },
  { id: "collaboration", file: "多人协作功能介绍.md", label: "多人协作" },
  { id: "editing", file: "剪辑工作台联动说明.md", label: "剪辑联动" },
  { id: "venv-slim", file: "后端虚拟环境瘦身报告.md", label: "环境瘦身" },
];

export default function Guide() {
  const [activeTab, setActiveTab] = useState(DOC_FILES[0].id);
  const [contents, setContents] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const navigate = useNavigate();

  const loadDoc = async (file: string, id: string) => {
    if (contents[id] || loading[id]) return;
    setLoading((prev) => ({ ...prev, [id]: true }));
    try {
      const resp = await fetch(`/docs/${encodeURIComponent(file)}`);
      if (resp.ok) {
        const text = await resp.text();
        setContents((prev) => ({ ...prev, [id]: text }));
      } else {
        setContents((prev) => ({ ...prev, [id]: "文档加载失败" }));
      }
    } catch {
      setContents((prev) => ({ ...prev, [id]: "文档加载失败" }));
    } finally {
      setLoading((prev) => ({ ...prev, [id]: false }));
    }
  };

  useEffect(() => {
    loadDoc(DOC_FILES[0].file, DOC_FILES[0].id);
  }, []);

  const handleTabClick = (id: string, file: string) => {
    setActiveTab(id);
    loadDoc(file, id);
  };

  const renderMarkdown = (text: string) => {
    // 简单的 markdown 渲染
    return text
      .split("\n")
      .map((line, i) => {
        // 标题
        if (line.startsWith("# ")) {
          return `<h1 class="text-2xl font-bold mb-4 mt-6 text-foreground">${line.slice(2)}</h1>`;
        }
        if (line.startsWith("## ")) {
          return `<h2 class="text-xl font-semibold mb-3 mt-5 text-foreground border-b border-border/30 pb-2">${line.slice(3)}</h2>`;
        }
        if (line.startsWith("### ")) {
          return `<h3 class="text-lg font-medium mb-2 mt-4 text-foreground">${line.slice(4)}</h3>`;
        }
        // 列表
        if (line.startsWith("- ")) {
          return `<li class="ml-4 mb-1 text-foreground/80">${line.slice(2)}</li>`;
        }
        // 代码块
        if (line.startsWith("```")) {
          return "";
        }
        // 链接
        const linked = line.replace(
          /\[([^\]]+)\]\(([^)]+)\)/g,
          '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-primary hover:underline">$1</a>'
        );
        // 加粗
        const bolded = linked.replace(
          /\*\*([^*]+)\*\*/g,
          '<strong class="font-semibold text-foreground">$1</strong>'
        );
        // 空行
        if (line.trim() === "") {
          return "<br />";
        }
        return `<p class="mb-2 text-foreground/80 leading-relaxed">${bolded}</p>`;
      })
      .join("");
  };

  const activeDoc = DOC_FILES.find((d) => d.id === activeTab);

  return (
    <div className="flex flex-col h-[calc(100vh-64px)] bg-background">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border/30 bg-card/30 flex-shrink-0">
        <button
          onClick={() => navigate(-1)}
          className="p-1.5 rounded-lg border border-border/40 text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-all"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-primary" />
          <h1 className="text-sm font-semibold text-foreground">使用向导</h1>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 px-4 py-2 border-b border-border/30 bg-card/20 flex-shrink-0 overflow-x-auto">
        {DOC_FILES.map((doc) => (
          <button
            key={doc.id}
            onClick={() => handleTabClick(doc.id, doc.file)}
            className={cn(
              "px-3 py-1.5 text-xs font-medium rounded-md whitespace-nowrap transition-all",
              activeTab === doc.id
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-accent/60"
            )}
          >
            {doc.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {loading[activeTab] ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="w-6 h-6 animate-spin text-primary" />
          </div>
        ) : contents[activeTab] ? (
          <div
            className="max-w-3xl mx-auto prose prose-sm"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(contents[activeTab]) }}
          />
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            选择一个文档开始阅读
          </div>
        )}
      </div>
    </div>
  );
}
