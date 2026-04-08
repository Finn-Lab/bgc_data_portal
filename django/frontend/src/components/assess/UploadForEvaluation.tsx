import { useState, useRef, useCallback } from "react";
import { Upload, FileArchive, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useUploadAssessment } from "@/hooks/use-upload-assessment";

type UploadType = "bgc" | "assembly";

export function UploadForEvaluation() {
  const [uploadType, setUploadType] = useState<UploadType>("bgc");
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const { upload, isUploading, error } = useUploadAssessment();

  const handleFile = useCallback((f: File | undefined) => {
    if (!f) return;
    setFile(f);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      handleFile(e.dataTransfer.files[0]);
    },
    [handleFile],
  );

  const handleSubmit = () => {
    if (!file) return;
    upload({ type: uploadType, file });
  };

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold tracking-tight">
        Upload for Evaluation
      </h3>

      {/* Type selector */}
      <div className="flex gap-2">
        {(["bgc", "assembly"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setUploadType(t)}
            className={`flex-1 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
              uploadType === t
                ? "border-primary bg-primary text-primary-foreground"
                : "border-input hover:bg-accent"
            }`}
          >
            {t === "bgc" ? "Single BGC" : "Assembly"}
          </button>
        ))}
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-4 text-center transition-colors ${
          dragOver
            ? "border-primary bg-primary/5"
            : "border-muted-foreground/25 hover:border-muted-foreground/50"
        }`}
      >
        {file ? (
          <>
            <FileArchive className="h-5 w-5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground truncate max-w-full">
              {file.name}
            </span>
          </>
        ) : (
          <>
            <Upload className="h-5 w-5 text-muted-foreground" />
            <span className="text-xs text-muted-foreground">
              Drop .tar.gz or click
            </span>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".tar.gz,.tgz"
          className="hidden"
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </div>

      {/* Submit */}
      <Button
        onClick={handleSubmit}
        disabled={!file || isUploading}
        className="w-full"
        size="sm"
      >
        {isUploading ? (
          <>
            <Loader2 className="mr-2 h-3 w-3 animate-spin" />
            Processing…
          </>
        ) : (
          "Submit for Evaluation"
        )}
      </Button>

      {error && (
        <p className="text-xs text-destructive">{error}</p>
      )}
    </div>
  );
}
