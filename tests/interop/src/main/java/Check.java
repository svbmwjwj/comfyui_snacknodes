import org.cryptomator.cryptofs.*;
import org.cryptomator.cryptolib.api.*;
import org.cryptomator.cryptolib.common.MasterkeyFileAccess;
import java.net.URI;
import java.nio.file.*;
import java.security.*;
import java.util.HexFormat;

public class Check {
  public static void main(String[] a) throws Exception {
    String mode = a[0]; Path vault = Path.of(a[1]); String pw = System.getenv("PW");
    SecureRandom rnd = SecureRandom.getInstanceStrong();
    MasterkeyFileAccess mfa = new MasterkeyFileAccess(new byte[0], rnd);
    MasterkeyLoader loader = keyId -> { try { return mfa.load(vault.resolve("masterkey.cryptomator"), pw); } catch (Exception e) { throw new MasterkeyLoadingFailedException("load", e); } };
    var props = CryptoFileSystemProperties.cryptoFileSystemProperties().withKeyLoader(loader).build();
    if (mode.equals("create")) {   // create vault + files with official lib
      Files.createDirectories(vault);
      try (Masterkey mk = Masterkey.generate(rnd)) { mfa.persist(mk, vault.resolve("masterkey.cryptomator"), pw); }
      CryptoFileSystemProvider.initialize(vault, props, URI.create("masterkeyfile:masterkey.cryptomator"));
      try (FileSystem fs = CryptoFileSystemProvider.newFileSystem(vault, props)) {
        Files.createDirectories(fs.getPath("/ComfyUI/existing"));
        Files.writeString(fs.getPath("/ComfyUI/existing/hello.txt"), "made by cryptofs");
      }
      return;
    }
    try (FileSystem fs = CryptoFileSystemProvider.newFileSystem(vault, props)) {  // list + hash
      try (var w = Files.walk(fs.getPath("/"))) {
        for (Path p : (Iterable<Path>) w.sorted()::iterator) {
          if (Files.isRegularFile(p)) {
            byte[] d = Files.readAllBytes(p);
            System.out.println("F\t" + p + "\t" + d.length + "\t" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(d)));
          } else System.out.println("D " + p);
        }
      }
    }
  }
}
