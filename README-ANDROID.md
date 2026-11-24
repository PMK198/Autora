# AUTORA Android 6.0 – telepítőprojekt
A meglévő Render webalkalmazást jeleníti meg. A Python szervert nem írja felül.
1. A GitHub PMK198/Autora tároló gyökerébe töltsd fel az android mappát és a .github/workflows/android-apk.yml fájlt, az útvonalak megtartásával. A rejtett .github mappát szükség esetén a GitHub Add file / Create new file funkcióval hozd létre a teljes útvonal beírásával.
2. Settings / Secrets and variables / Actions / New repository secret: AUTORA_KEYSTORE_B64 és AUTORA_KEY_PASSWORD. A külön privát csomag megfelelő TXT fájljainak teljes tartalmát másold be. A privát csomagot soha ne töltsd fel a repóba!
3. Actions / AUTORA Android APK / Run workflow / main / Run workflow. Siker esetén az Artifacts alatt AUTORA-Android letöltése, kibontása, AUTORA.apk telepítése. Androidon engedélyezd az adott fájlkezelő számára az ismeretlen alkalmazások telepítését, majd kapcsold vissza.
4. Szerverfrissítéshez nem kell APK. Android-kód módosításakor növeld a versionCode értékét az android/app/build.gradle fájlban, és használd ugyanazt a két titkot. Korábbi eltérő aláírású APK nem frissíthető helyben.
A projekt nem tartalmaz új fórumot, felhasználói rendszert vagy további katalógusfunkciót. A szerver meglévő funkcióit használja. A build itt nem futott le; a GitHub workflow végzi a fordítást és az aláírás ellenőrzését.
