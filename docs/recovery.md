# Getting your passwords back

Your vault is a standard KeePass file (KDBX 4), so almost every recovery path ends in
[KeePassXC](https://keepassxc.org/), which opens it with your master password. There is no other
way in: **a forgotten master password cannot be recovered, by design.**

## Which situation are you in?

| What happened | What to do |
| --- | --- |
| The extension misbehaves but the vault is there | Reload it at `chrome://extensions`. The vault is kept; a reload only locks it. |
| The extension or the browser profile is gone, but sync to Google Drive was on | Load the extension again, set the Google OAuth client ID (Settings), then on the vault page open **Open a vault that is already on Google Drive** and type that vault's master password (setup guide, section 4). |
| You want to read the passwords without the extension | Download `vault.kdbx` from Drive (`PersonalVault` folder), or use **Export encrypted copy**, and open it in KeePassXC with the master password. |
| The file on Google Drive is damaged or was rolled back | In Drive, right-click the file → **Manage versions** and download an earlier version; open it in KeePassXC. Drive keeps versions of every upload. |
| The vault in the browser is damaged | The extension never replaces a vault with bytes it could not read back, and keeps the 20 previous copies in its storage. On the vault page, **Backups → Show backups** lists them: pick one and **Restore** (a backup from before a master-password change asks for the old password; the vault you replace becomes the newest backup, so a restore can be undone). Or get the file from Drive, as above. |
| Both copies changed on two devices | The Google Drive panel offers **Merge both copies**, **Keep this computer's copy** or **Take the Google Drive copy**; the other copy stays in Drive's version history. |
| You deleted a login by mistake | Vault page → **Recycle Bin** → **Restore**. (Anything you deleted for good is gone; an earlier backup may still hold it.) |
| You overwrote a password by mistake | Open the login → **Earlier versions** → **Restore this version**. |

## The three paths to practise before you need them

Do these once with a fake vault, not with the real one:

1. **Open it in KeePassXC.** Export an encrypted copy from the vault page (Profile → Export),
   open it in KeePassXC with the master password. Every login, with its URLs and history, is
   there; the hidden `.app` group, if any, is the old desktop app's and can be ignored.
2. **Bring it back from Drive.** Make a vault with Drive sync on and a login in it, then delete the
   profile on the vault page, and bring it back with **Open a vault that is already on Google
   Drive**.
3. **Go back a version.** Edit a login twice, then in Drive download the older version and open it
   in KeePassXC.

## Keep a copy outside the browser

Removing the extension, clearing its data, or losing the browser profile deletes the vaults kept in
the browser. Turn on Google Drive sync, and from time to time export an encrypted copy to a place
you control. Write down where the copy is and which master password opens it; **do not** write the
master password next to it.
