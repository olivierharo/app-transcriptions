<?php

namespace App\Service;

use App\Entity\Compte;
use App\Entity\Depot;
use App\Repository\DepotRepository;
use Doctrine\ORM\EntityManagerInterface;
use Symfony\Component\DependencyInjection\Attribute\Autowire;

/**
 * Stockage des depots : fichiers audio dans var/boites/<compte>/, metadonnees
 * en base. Toute erreur destinee a l'utilisateur est levee en \DomainException.
 */
class Boites
{
    public const EXTS = ['.m4a', '.aac', '.mp3', '.wav', '.ogg', '.opus', '.webm', '.flac', '.mp4', '.caf'];
    public const TYPES = [
        'audio/x-m4a' => '.m4a', 'audio/m4a' => '.m4a', 'audio/mp4' => '.m4a', 'audio/aac' => '.aac',
        'audio/mpeg' => '.mp3', 'audio/mp3' => '.mp3', 'audio/wav' => '.wav', 'audio/x-wav' => '.wav',
        'audio/wave' => '.wav', 'audio/ogg' => '.ogg', 'audio/webm' => '.webm', 'audio/flac' => '.flac',
        'video/mp4' => '.m4a', 'video/quicktime' => '.m4a', 'audio/x-caf' => '.caf',
    ];
    /** Signatures des formats audio acceptes (cherchees dans les 16 premiers octets). */
    private const SIGNATURES = ['ftyp', 'RIFF', 'ID3', 'OggS', 'fLaC', "\x1aE\xdf\xa3", 'caff',
        "\xff\xfb", "\xff\xf3", "\xff\xf2", "\xff\xf1", "\xff\xf9"];

    public function __construct(
        private EntityManagerInterface $em,
        private DepotRepository $depots,
        #[Autowire('%kernel.project_dir%/var/boites')] private string $racine,
        #[Autowire('%env(int:RELAIS_TAILLE_MAX_MO)%')] private int $tailleMaxMo,
        #[Autowire('%env(int:RELAIS_QUOTA_MO)%')] private int $quotaMo,
    ) {
    }

    public function dossier(Compte $compte): string
    {
        $d = $this->racine.'/'.$compte->getNom();
        if (!is_dir($d)) {
            mkdir($d, 0770, true);
        }

        return $d;
    }

    public function chemin(Depot $depot): string
    {
        return $this->dossier($depot->getCompte()).'/'.$depot->getId().$depot->getExt();
    }

    /**
     * Enregistre le flux $entree (corps brut de la requete) comme nouveau depot.
     *
     * @param resource $entree
     */
    public function deposer(Compte $compte, $entree, int $annonce, string $nom, string $titre, string $type): Depot
    {
        $max = $this->tailleMaxMo * 1024 ** 2;
        $limitePhp = self::octets((string) ini_get('post_max_size'));
        if ($annonce > $max || ($limitePhp > 0 && $annonce > $limitePhp)) {
            throw new \DomainException('Fichier trop volumineux pour le serveur.');
        }
        if ($this->depots->volume($compte) + $annonce > $this->quotaMo * 1024 ** 2) {
            throw new \DomainException("Boîte pleine : ouvrez l'application sur l'ordinateur pour la vider.");
        }

        $nom = mb_substr(basename($nom), 0, 120);
        $ext = strtolower(strrchr($nom, '.') ?: '');
        if (!in_array($ext, self::EXTS, true)) {
            $ext = self::TYPES[strtolower(trim(explode(';', $type)[0]))] ?? '.m4a';
        }
        $id = date('Ymd-His-').bin2hex(random_bytes(4));
        $partiel = $this->dossier($compte).'/'.$id.'.part';
        $sortie = fopen($partiel, 'wb');
        $recu = 0;
        $debut = '';
        try {
            while (!feof($entree)) {
                $bloc = fread($entree, 1 << 20);
                if ($bloc === false || $bloc === '') {
                    break;
                }
                $recu += strlen($bloc);
                if ($recu > $max) {
                    throw new \DomainException('Fichier trop volumineux.');
                }
                if (strlen($debut) < 16) {
                    $debut .= substr($bloc, 0, 16);
                }
                fwrite($sortie, $bloc);
            }
            fclose($sortie);
            if ($recu === 0) {
                throw new \DomainException('Fichier vide.');
            }
            if (!$this->estAudio(substr($debut, 0, 16))) {
                throw new \DomainException("Ce fichier n'est pas un enregistrement audio reconnu.");
            }
            $depot = new Depot($id, $compte, $ext, $nom, mb_substr(trim($titre), 0, 120), $recu);
            rename($partiel, $this->chemin($depot));
        } catch (\Throwable $e) {
            if (is_resource($sortie)) {
                fclose($sortie);
            }
            @unlink($partiel);
            throw $e;
        }
        $this->em->persist($depot);
        $this->em->flush();

        return $depot;
    }

    public function supprimer(Depot $depot): void
    {
        @unlink($this->chemin($depot));
        $this->em->remove($depot);
        $this->em->flush();
    }

    /** Code de connexion a coller dans l'application de bureau. */
    public static function codeConnexion(string $url, string $nom, string $envoi, string $retrait): string
    {
        $json = json_encode(['u' => rtrim($url, '/'), 'n' => $nom, 'e' => $envoi, 'r' => $retrait],
            JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);

        return 'TR1-'.rtrim(strtr(base64_encode($json), '+/', '-_'), '=');
    }

    private function estAudio(string $debut): bool
    {
        foreach (self::SIGNATURES as $signature) {
            if (str_contains($debut, $signature)) {
                return true;
            }
        }

        return false;
    }

    private static function octets(string $valeur): int
    {
        $n = (int) $valeur;

        return match (strtoupper(substr(trim($valeur), -1))) {
            'G' => $n * 1024 ** 3, 'M' => $n * 1024 ** 2, 'K' => $n * 1024, default => $n,
        };
    }
}
