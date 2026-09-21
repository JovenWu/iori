"use client";

import { AppSidebar } from "@/components/app-sidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { useAuth } from "@/lib/auth";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // AuthProvider owns the /login redirect — here we just hold render until
  // the session state is known so the sidebar never flashes for guests.
  const { token, isLoading } = useAuth();

  if (isLoading || !token) {
    return <div className="min-h-svh bg-background" />;
  }

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>{children}</SidebarInset>
    </SidebarProvider>
  );
}
