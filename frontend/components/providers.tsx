"use client"

import { TooltipProvider } from "@/components/ui/tooltip"
import { Toaster } from "@/components/ui/sonner"
import { AuthProvider } from "@/lib/auth"
import { SettingsProvider } from "@/lib/settings"

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <SettingsProvider>
        <TooltipProvider>
          {children}
          {/* Inside SettingsProvider — the toast theme follows the app's
              theme preference, not the OS. */}
          <Toaster position="bottom-right" />
        </TooltipProvider>
      </SettingsProvider>
    </AuthProvider>
  )
}
