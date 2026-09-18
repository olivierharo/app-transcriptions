<?php

namespace App\Repository;

use App\Entity\Compte;
use Doctrine\Bundle\DoctrineBundle\Repository\ServiceEntityRepository;
use Doctrine\Persistence\ManagerRegistry;

/** @extends ServiceEntityRepository<Compte> */
class CompteRepository extends ServiceEntityRepository
{
    public function __construct(ManagerRegistry $registry)
    {
        parent::__construct($registry, Compte::class);
    }

    /** @return array{0: ?Compte, 1: ?string} [compte, 'envoi'|'retrait'] */
    public function identifier(string $cle): array
    {
        if ($cle === '') {
            return [null, null];
        }
        $empreinte = Compte::empreinte($cle);
        if ($c = $this->findOneBy(['empreinteEnvoi' => $empreinte])) {
            return [$c, 'envoi'];
        }
        if ($c = $this->findOneBy(['empreinteRetrait' => $empreinte])) {
            return [$c, 'retrait'];
        }

        return [null, null];
    }
}
