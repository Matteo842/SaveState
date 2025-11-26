# Privacy Policy for SaveState

**Last Updated:** November 26, 2025

SaveState ("the Application") is an open-source application developed by Matteo842. This Privacy Policy explains how the Application handles your data, specifically regarding Google Drive integration.

## 1. Data Collection and Usage
SaveState is designed with privacy as a priority. 
- **No Personal Data Collection:** The Application does not collect, store, or transmit any personal information, usage statistics, or telemetry data to the developer or any third-party servers.
- **Local Operation:** All operations, including backup creation and file management, are performed locally on your device.

## 2. Google Drive Integration
The Application offers an optional feature to synchronize your save files with your personal Google Drive account.
- **Authentication:** Authentication is handled directly via Google's OAuth 2.0 servers. The Application receives an access token which is stored locally on your device (in a `token.pickle` file). This token is never sent to the developer.
- **Limited Access (Scopes):** The Application requests the restricted scope `https://www.googleapis.com/auth/drive.file`. This ensures that SaveState can **only** access and modify files and folders that it has created itself. It **cannot** view, modify, or delete any other files in your Google Drive.
- **Data Transmission:** Backup files are encrypted (HTTPS) during transmission directly between your device and Google Drive. No intermediate servers are used.

## 3. Data Storage
- **Local:** Configuration files and local backups are stored on your device in the Application's directory.
- **Cloud:** Cloud backups are stored in a dedicated folder named "SaveState Backups" within your personal Google Drive storage. You retain full ownership and control over these files.

## 4. Third-Party Services
The Application uses Google Drive API Services. Use of Google Drive is subject to Google's Privacy Policy and Terms of Service.

## 5. Contact
If you have any questions about this Privacy Policy, please contact the developer via the GitHub repository issue tracker: https://github.com/Matteo842/SaveState/issues