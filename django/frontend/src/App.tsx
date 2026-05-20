import { Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";
import { IbgcDashboard } from "@/components/discovery/IbgcDashboard";
import { DashboardShell } from "@/components/DashboardShell";
import { ReportPage } from "@/components/report/ReportPage";
import { useUrlSync } from "@/hooks/use-url-sync";

function App() {
  useUrlSync();

  return (
    <>
      <Routes>
        {/* v2 Discovery dashboard (iBGC-first). */}
        <Route path="/" element={<IbgcDashboard />} />
        {/* Shortlist Report — opened in a new tab via Generate Report. */}
        <Route path="/report" element={<ReportPage />} />
        {/* Legacy Explore/Query/Assess modes — preserved at /legacy until P4
            cleanup removes them. */}
        <Route path="/legacy/*" element={<DashboardShell />} />
        <Route path="*" element={<IbgcDashboard />} />
      </Routes>
      <Toaster position="bottom-right" />
    </>
  );
}

export default App;
