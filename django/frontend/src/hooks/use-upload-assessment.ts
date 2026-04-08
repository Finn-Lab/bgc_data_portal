import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { postUploadAssessment } from "@/api/assessment";
import { useAssessStore } from "@/stores/assess-store";
import { useModeStore } from "@/stores/mode-store";

export function useUploadAssessment() {
  const startUploadAssessment = useAssessStore(
    (s) => s.startUploadAssessment,
  );
  const setTaskId = useAssessStore((s) => s.setTaskId);
  const setStatus = useAssessStore((s) => s.setStatus);
  const setMode = useModeStore((s) => s.setMode);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: ({ type, file }: { type: "bgc" | "assembly"; file: File }) =>
      postUploadAssessment(type, file),
    onSuccess: (data) => {
      setError(null);
      startUploadAssessment(
        data.asset_type as "assembly" | "bgc",
        "Uploaded file",
      );
      setTaskId(data.task_id);
      setMode("assess");
    },
    onError: (err: Error) => {
      setError(err.message || "Upload failed");
      setStatus("error");
    },
  });

  return {
    upload: mutation.mutate,
    isUploading: mutation.isPending,
    error,
  };
}
