import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';

export interface OutletContextType {
  onNewRelease: () => void;
}

interface LayoutProps {
  outletContext: OutletContextType;
}

export default function Layout({ outletContext }: LayoutProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className={`app-layout ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((prev) => !prev)}
      />
      <main className="app-main">
        <Outlet context={outletContext} />
      </main>
    </div>
  );
}
