import { LogLevel, type Configuration } from '@azure/msal-browser';

const clientId = import.meta.env.VITE_AZURE_AD_CLIENT_ID;
const tenantId = import.meta.env.VITE_AZURE_AD_TENANT_ID;
const redirectUri =
  import.meta.env.VITE_AZURE_AD_REDIRECT_URI?.trim() || window.location.origin;
const postLogoutRedirectUri =
  import.meta.env.VITE_AZURE_AD_POST_LOGOUT_REDIRECT_URI?.trim() ||
  `${redirectUri.replace(/\/$/, '')}/login`;

if (!clientId || !tenantId) {
  console.warn(
    'Missing VITE_AZURE_AD_CLIENT_ID or VITE_AZURE_AD_TENANT_ID. Microsoft login will not work until these are set.',
  );
}

/** Exact URI that must be registered in Azure AD → App registration → Authentication → SPA. */
export const azureRedirectUri = redirectUri;

export const msalConfig: Configuration = {
  auth: {
    clientId: clientId ?? '',
    authority: tenantId
      ? `https://login.microsoftonline.com/${tenantId}`
      : 'https://login.microsoftonline.com/common',
    redirectUri,
    postLogoutRedirectUri,
  },
  cache: {
    cacheLocation: 'sessionStorage',
  },
  system: {
    loggerOptions: {
      logLevel: LogLevel.Warning,
    },
  },
};

export const loginRequest = {
  scopes: ['User.Read', 'openid', 'profile', 'email'],
};
