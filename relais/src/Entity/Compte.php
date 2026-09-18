<?php

namespace App\Entity;

use App\Repository\CompteRepository;
use Doctrine\ORM\Mapping as ORM;

/**
 * Membre de l'equipe et sa boite aux lettres.
 *
 * Les cles ne sont jamais stockees en clair : seulement leur empreinte SHA-256.
 * La cle d'envoi (iPhone) ne permet que de deposer ; la cle de retrait (PC)
 * permet de lister, telecharger et supprimer.
 */
#[ORM\Entity(repositoryClass: CompteRepository::class)]
class Compte
{
    #[ORM\Id]
    #[ORM\GeneratedValue]
    #[ORM\Column]
    private ?int $id = null;

    #[ORM\Column(length: 40, unique: true)]
    private string $nom;

    #[ORM\Column(length: 64, unique: true)]
    private string $empreinteEnvoi;

    #[ORM\Column(length: 64, unique: true)]
    private string $empreinteRetrait;

    #[ORM\Column]
    private \DateTimeImmutable $creeLe;

    public function __construct(string $nom)
    {
        $this->nom = $nom;
        $this->creeLe = new \DateTimeImmutable();
    }

    public function getId(): ?int { return $this->id; }
    public function getNom(): string { return $this->nom; }
    public function getCreeLe(): \DateTimeImmutable { return $this->creeLe; }

    /** Genere de nouvelles cles ; retourne [envoi, retrait] en clair (seule occasion de les voir). */
    public function renouvelerCles(): array
    {
        $envoi = self::cleAleatoire();
        $retrait = self::cleAleatoire();
        $this->empreinteEnvoi = self::empreinte($envoi);
        $this->empreinteRetrait = self::empreinte($retrait);

        return [$envoi, $retrait];
    }

    public static function empreinte(string $cle): string
    {
        return hash('sha256', $cle);
    }

    private static function cleAleatoire(): string
    {
        return rtrim(strtr(base64_encode(random_bytes(24)), '+/', '-_'), '=');
    }
}
