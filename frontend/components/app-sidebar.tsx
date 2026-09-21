"use client"

import * as React from "react"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import { NavUser } from "@/components/nav-user"
import { SidebarHeaderContent } from "@/components/sidebar-header"
import { SidebarThreads } from "@/components/sidebar-threads"
import { useAuth } from "@/lib/auth"

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const { user } = useAuth()
  const displayName = user?.name ?? user?.username ?? "User"

  return (
    <Sidebar variant="inset" {...props}>
      <SidebarHeader>
        <SidebarHeaderContent />
      </SidebarHeader>
      <SidebarContent>
        <SidebarThreads />
      </SidebarContent>
      <SidebarFooter>
        <NavUser
          user={{
            name: displayName,
            identifier: user?.username ? `@${user.username}` : "",
          }}
        />
      </SidebarFooter>
    </Sidebar>
  )
}
