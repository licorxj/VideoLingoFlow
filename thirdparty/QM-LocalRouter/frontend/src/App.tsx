import React from "react";
import { Routes, Route } from "react-router-dom";
import Sidebar from "./components/layout/Sidebar";
import { Toaster } from "./components/ui/toaster";
import Dashboard from "./pages/Dashboard";
import Providers from "./pages/Providers";
import Strategies from "./pages/Strategies";
import Logs from "./pages/Logs";
import SettingsPage from "./pages/Settings";
import Chat from "./pages/Chat";

export default function App() {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <main className="ml-60 flex-1 p-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/providers" element={<Providers />} />
          <Route path="/strategies" element={<Strategies />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
      <Toaster />
    </div>
  );
}
