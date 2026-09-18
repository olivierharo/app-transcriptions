<?php

namespace App\Entity;

use App\Repository\DepotRepository;
use Doctrine\ORM\Mapping as ORM;

/**
 * Enregistrement depose par l'iPhone, en attente de releve par le PC.
 * Le fichier audio est dans var/boites/<compte>/<id><ext>.
 */
#[ORM\Entity(repositoryClass: DepotRepository::class)]
#[ORM\Index(columns: ['date_depot'])]
class Depot
{
    #[ORM\Id]
    #[ORM\Column(length: 40)]
    private string $id;

    #[ORM\ManyToOne]
    #[ORM\JoinColumn(nullable: false, onDelete: 'CASCADE')]
    private Compte $compte;

    #[ORM\Column(length: 8)]
    private string $ext;

    #[ORM\Column(length: 120)]
    private string $nomOriginal;

    #[ORM\Column(length: 120)]
    private string $titre;

    #[ORM\Column(type: 'bigint')]
    private string $taille;

    #[ORM\Column]
    private \DateTimeImmutable $dateDepot;

    public function __construct(string $id, Compte $compte, string $ext, string $nomOriginal, string $titre, int $taille)
    {
        $this->id = $id;
        $this->compte = $compte;
        $this->ext = $ext;
        $this->nomOriginal = $nomOriginal;
        $this->titre = $titre;
        $this->taille = (string) $taille;
        $this->dateDepot = new \DateTimeImmutable();
    }

    public function getId(): string { return $this->id; }
    public function getCompte(): Compte { return $this->compte; }
    public function getExt(): string { return $this->ext; }
    public function getTaille(): int { return (int) $this->taille; }
    public function getDateDepot(): \DateTimeImmutable { return $this->dateDepot; }

    /** Format attendu par l'application de bureau (src/app/relais.py). */
    public function versTableau(): array
    {
        return [
            'id' => $this->id,
            'ext' => $this->ext,
            'nom' => $this->nomOriginal,
            'titre' => $this->titre,
            'taille' => (int) $this->taille,
            'date' => $this->dateDepot->format('Y-m-d\TH:i:s'),
        ];
    }
}
