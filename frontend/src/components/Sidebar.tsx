import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import PortalLogo from './PortalLogo';

const navItems = [
  {
    label: 'Dashboard',
    path: '/',
    match: (pathname: string) => pathname === '/' || pathname.startsWith('/release/'),
    icon: (
      <svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
        <path d="M1 2.75A1.75 1.75 0 0 1 2.75 1h10.5A1.75 1.75 0 0 1 15 2.75v10.5A1.75 1.75 0 0 1 13.25 15H2.75A1.75 1.75 0 0 1 1 13.25V2.75zm1.75-.25a.25.25 0 0 0-.25.25v10.5c0 .138.112.25.25.25h10.5a.25.25 0 0 0 .25-.25V2.75a.25.25 0 0 0-.25-.25H2.75zM4 5.5a.75.75 0 0 1 .75-.75h6.5a.75.75 0 0 1 0 1.5h-6.5A.75.75 0 0 1 4 5.5zm0 3a.75.75 0 0 1 .75-.75h6.5a.75.75 0 0 1 0 1.5h-6.5A.75.75 0 0 1 4 8.5z" />
      </svg>
    ),
  },
  {
    label: 'Approval Queue',
    path: '/approvals',
    match: (pathname: string) => pathname === '/approvals',
    icon: (
      <svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
        <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm0 1.5a5.5 5.5 0 1 1 0 11 5.5 5.5 0 0 1 0-11zm-.75 2.75a.75.75 0 0 1 1.5 0v2.25H11a.75.75 0 0 1 0 1.5H8.75V11a.75.75 0 0 1-1.5 0V8.75H5a.75.75 0 0 1 0-1.5h2.25V5.25z" />
      </svg>
    ),
  },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const location = useLocation();
  const { user, logout } = useAuth();

  return (
    <aside className={`app-sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-brand">
        <button
          type="button"
          className="sidebar-brand-button"
          onClick={onToggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <PortalLogo size={collapsed ? 36 : 40} />
          {!collapsed && (
            <div className="sidebar-brand-text">
              <h1 className="sidebar-title">Release Management Portal</h1>
              
            </div>
          )}
        </button>
        <button
          type="button"
          className="sidebar-toggle"
          onClick={onToggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            {collapsed ? (
              <path d="M6.78 3.97a.75.75 0 0 1 0 1.06L3.81 8l2.97 2.97a.75.75 0 1 1-1.06 1.06L2.22 8.53a.75.75 0 0 1 0-1.06l3.5-3.5a.75.75 0 0 1 1.06 0zm4.44 0a.75.75 0 0 1 1.06 0l3.5 3.5a.75.75 0 0 1 0 1.06l-3.5 3.5a.75.75 0 0 1-1.06-1.06L12.19 8 9.22 5.03a.75.75 0 0 1 0-1.06z" />
            ) : (
              <path d="M9.22 3.97a.75.75 0 0 1 0 1.06L12.19 8l-2.97 2.97a.75.75 0 1 0 1.06 1.06l3.5-3.5a.75.75 0 0 0 0-1.06l-3.5-3.5a.75.75 0 0 0-1.06 0zM3.78 3.97a.75.75 0 0 0 0 1.06L6.75 8 3.78 10.97a.75.75 0 1 0 1.06 1.06l3.5-3.5a.75.75 0 0 0 0-1.06l-3.5-3.5a.75.75 0 0 0-1.06 0z" />
            )}
          </svg>
        </button>
      </div>

      <nav className="sidebar-nav">
        {navItems.map((item) => {
          const isActive = item.match(location.pathname);
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`sidebar-tab ${isActive ? 'active' : ''}`}
              title={collapsed ? item.label : undefined}
            >
              <span className="sidebar-tab-icon">{item.icon}</span>
              {!collapsed && <span className="sidebar-tab-label">{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {!collapsed && user && (
        <div className="sidebar-user">
          <div className="sidebar-user-info">
            <span className="sidebar-user-name">{user.name}</span>
            <span className="sidebar-user-email">{user.email}</span>
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-sm sidebar-logout"
            onClick={() => void logout()}
          >
            Sign out
          </button>
        </div>
      )}
    </aside>
  );
}
