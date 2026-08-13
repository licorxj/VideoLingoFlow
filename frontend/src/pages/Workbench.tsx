import { useSearchParams } from "react-router-dom";
import WorkflowEditor from "@/components/workflow/WorkflowEditor";

export default function Workbench() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get("task") || undefined;

  return (
    <div className="h-full">
      <WorkflowEditor taskId={taskId} />
    </div>
  );
}
